import asyncio
import json
from collections.abc import Callable
from hashlib import sha256
from typing import Annotated, Any, Final, Literal, cast, final, override
from uuid import UUID

import httpx
from pydantic import Field, model_validator
from reducto import APIConnectionError, APIStatusError, AsyncReducto
from reducto.types import SettingsParam
from reducto.types.shared_params.page_range import PageRange

from grafy_core.artifact_contracts import (
    MARKDOWN,
    RASTER_IMAGE,
    TEXT_VALUE,
    MarkdownValue,
)
from grafy_core.artifacts import ArtifactRef, NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.egress import EgressRejectedError, PinnedPublicAddressTransport
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValue,
    TableValueType,
)

from grafy_plugin_reducto.declaration import REDUCTO
from grafy_plugin_reducto.response import ParseChunk, ParseChunkList

REDUCTO_BASE_URL: Final = "https://platform.reducto.ai"
MAX_SOURCE_BYTES: Final = 50_000_000
MAX_RESULT_BYTES: Final = 64_000_000
TIMEOUT_GRACE_SECONDS: float = 30
# The overall deadline is the asyncio.timeout in `run`; this only caps one dial.
HTTP_TIMEOUT: Final = httpx.Timeout(None, connect=15.0)

IMAGE_EXTENSIONS: Final = {
    "image/bmp": ".bmp",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "image/webp": ".webp",
}
STATUS_GUIDANCE: Final = {
    400: "Check that the document URL is reachable and the requested pages exist.",
    401: "The provider did not accept the configured API key.",
    403: "The provider could not access the document, or the key may not use this endpoint.",
    429: "The provider rate limit or account quota was exceeded.",
}
BLOCK_COLUMNS: Final = (
    ("index", TableValueType.INTEGER),
    ("page", TableValueType.INTEGER),
    ("original_page", TableValueType.INTEGER),
    ("kind", TableValueType.TEXT),
    ("text", TableValueType.TEXT),
    ("confidence", TableValueType.TEXT),
    ("parse_confidence", TableValueType.NUMBER),
    ("left", TableValueType.NUMBER),
    ("top", TableValueType.NUMBER),
    ("width", TableValueType.NUMBER),
    ("height", TableValueType.NUMBER),
)


class ReductoOcrConfig(NodeConfig):
    model: Literal["r-1", "r-1-mini"] = Field(
        default="r-1",
        description=(
            "Reducto Parse model. Always sent, so a change to the provider's default "
            "cannot move existing graphs. r-1-mini does not accept spreadsheets."
        ),
    )
    page_start: int | None = Field(
        default=None,
        ge=1,
        description="First page to process, 1-indexed. Empty processes from page 1.",
    )
    page_end: int | None = Field(
        default=None,
        ge=1,
        description="Last page to process, 1-indexed. Empty processes to the end.",
    )
    table_format: Literal["md", "html"] = Field(
        default="md",
        description="Render tables as Markdown, or HTML for tables with merged cells.",
    )
    timeout_s: int = Field(
        default=300,
        ge=10,
        le=900,
        description=(
            "Maximum provider processing time in seconds. A run that outlives it is "
            "not resubmitted."
        ),
    )

    @model_validator(mode="after")
    def validate_page_range(self) -> "ReductoOcrConfig":
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must not precede page_start")
        return self


class ReductoOcrInput(NodeInput):
    document_url: Annotated[
        str | None,
        InPort(TEXT_VALUE),
        Field(
            description=(
                "HTTPS URL of a document Reducto can fetch, including a presigned "
                "URL. Leave empty when a raster image is connected."
            ),
        ),
    ] = None
    image: Annotated[
        ArtifactRef | None,
        InPort(RASTER_IMAGE),
        Field(
            description=(
                "Raster image to parse, uploaded to Reducto. Leave empty when a "
                "document URL is connected."
            ),
        ),
    ] = None


class ReductoOcrOutput(NodeOutput):
    markdown: Annotated[
        MarkdownValue,
        OutPort(MARKDOWN),
        Field(description="Parsed document as Markdown."),
    ]
    blocks: Annotated[
        Table,
        OutPort(TABLE_DATA),
        Field(
            description=(
                "One row per returned block: order, page, original page, provider "
                "block kind, content, confidence, and the page-normalized box."
            ),
        ),
    ]


class ReductoOcrError(UserFacingNodeError):
    pass


def build_parse_output(chunks: list[ParseChunk]) -> ReductoOcrOutput:
    rows: list[dict[str, TableValue]] = []
    for chunk in chunks:
        for block in chunk.blocks:
            confidence = block.granular_confidence
            rows.append(
                {
                    "index": len(rows),
                    "page": block.bbox.page,
                    "original_page": block.bbox.original_page,
                    "kind": block.type,
                    "text": block.content,
                    "confidence": block.confidence,
                    "parse_confidence": (
                        None if confidence is None else confidence.parse_confidence
                    ),
                    "left": block.bbox.left,
                    "top": block.bbox.top,
                    "width": block.bbox.width,
                    "height": block.bbox.height,
                }
            )
    return ReductoOcrOutput(
        markdown=MarkdownValue(markdown="\n\n".join(chunk.content for chunk in chunks)),
        blocks=Table(
            columns=[
                TableColumn(id=name, title=name, value_type=value_type)
                for name, value_type in BLOCK_COLUMNS
            ],
            rows=rows,
        ),
    )


def build_reducto_ocr_node(context: PluginRuntimeContext) -> "ReductoOcrNode":
    return ReductoOcrNode(
        uow=context.uow,
        storage=context.storage,
        node_secrets=context.node_secrets,
    )


@REDUCTO.node(
    operator_id="reducto.ocr.process",
    version=1,
    title="Reducto OCR",
    factory=build_reducto_ocr_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            description="Write-only bearer credential for the Reducto platform API.",
            config_dependencies=(),
        ),
    ),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=(REDUCTO_BASE_URL,),
        # A large result comes back as a presigned URL on the provider's storage.
        dynamic_destinations=True,
    ),
)
@final
class ReductoOcrNode(Node[ReductoOcrConfig, ReductoOcrInput, ReductoOcrOutput]):
    """Parses a document URL or raster image with the Reducto Parse API."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        node_secrets: NodeSecretResolverPort,
        transport_factory: Callable[
            [], httpx.AsyncBaseTransport
        ] = PinnedPublicAddressTransport,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._node_secrets = node_secrets
        self._transport_factory = transport_factory

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ReductoOcrConfig,
        inputs: ReductoOcrInput,
        /,
    ) -> ReductoOcrOutput:
        if (inputs.document_url is None) == (inputs.image is None):
            raise ReductoOcrError(
                "Reducto OCR requires exactly one of a document URL or a raster "
                f"image on node {context.node_id!r}"
            )
        # Also keeps the provider's own reducto:// and jobid:// inputs out of graphs.
        # The URL is never quoted: a presigned one carries its signature.
        if inputs.document_url is not None and not inputs.document_url.startswith(
            "https://"
        ):
            raise ReductoOcrError("document_url must use HTTPS")
        try:
            api_key = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                graph_id=context.graph_id,
                node_id=context.node_id,
                name="api_key",
                dependencies={},
            )
        except Exception as exc:
            raise ReductoOcrError(
                f"Reducto OCR could not resolve its API key for node {context.node_id!r}"
            ) from exc

        settings: SettingsParam = {
            "model": config.model,
            "timeout": float(config.timeout_s),
        }
        page_range: PageRange = {}
        if config.page_start is not None:
            page_range["start"] = config.page_start
        if config.page_end is not None:
            page_range["end"] = config.page_end
        if page_range:
            settings["page_range"] = page_range

        # Provider messages are never carried into an error: they can quote request
        # content back, and a graph run stores what it is given.
        try:
            async with asyncio.timeout(config.timeout_s + TIMEOUT_GRACE_SECONDS):
                async with (
                    httpx.AsyncClient(
                        timeout=HTTP_TIMEOUT,
                        follow_redirects=False,
                        transport=self._transport_factory(),
                    ) as http_client,
                    AsyncReducto(
                        api_key=api_key.get_secret_value(),
                        base_url=REDUCTO_BASE_URL,
                        http_client=http_client,
                        # One submission is one billable job.
                        max_retries=0,
                        timeout=HTTP_TIMEOUT,
                    ) as client,
                ):
                    if inputs.image is not None:
                        source = await self._upload_image(
                            client, inputs.image, context.workspace_id
                        )
                    else:
                        source = cast(str, inputs.document_url)
                    # Raw: the typed response picks its class by `response_type` and
                    # would need a dump back to JSON for ParseChunkList anyway.
                    raw = await client.parse.with_raw_response.run(
                        input=source,
                        formatting={"table_output_format": config.table_format},
                        retrieval={
                            "chunking": {"chunk_mode": "disabled", "chunk_overlap": 0}
                        },
                        settings=settings,
                    )
                    result = cast(dict[str, Any], await raw.json())["result"]
                    if result["type"] == "url":
                        chunks = await self._download_chunks(result["url"])
                    else:
                        chunks = ParseChunkList.validate_python(result["chunks"])
                    return build_parse_output(chunks)
        except ReductoOcrError:
            raise
        except TimeoutError:
            raise ReductoOcrError(
                "Reducto did not answer within its time budget. It may still be "
                "working, and this node does not resubmit: raise timeout_s or parse "
                "a smaller page range."
            ) from None
        except APIStatusError as exc:
            guidance = STATUS_GUIDANCE.get(exc.status_code, "")
            raise ReductoOcrError(
                f"Reducto returned HTTP {exc.status_code}. {guidance}".strip()
            ) from None
        except (KeyError, TypeError, ValueError):
            raise ReductoOcrError(
                "Reducto returned a result that does not match the Parse contract"
            ) from None
        except Exception as exc:
            # The SDK wraps what its transport raised, one level down.
            if isinstance(exc, EgressRejectedError) or isinstance(
                exc.__cause__, EgressRejectedError
            ):
                raise ReductoOcrError(
                    "Reducto request was blocked by this deployment's egress policy"
                ) from None
            if isinstance(exc, APIConnectionError | httpx.TransportError):
                raise ReductoOcrError("Reducto could not be reached") from None
            raise ReductoOcrError(
                f"Reducto OCR failed for node {context.node_id!r}"
            ) from None

    async def _upload_image(
        self, client: AsyncReducto, ref: ArtifactRef, workspace_id: UUID
    ) -> str:
        try:
            async with self._uow as uow:
                artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
            if (
                artifact is None
                or artifact.ref() != ref
                or artifact.bucket is None
                or artifact.object_key is None
            ):
                raise ReductoOcrError(f"Raster image {ref.artifact_id} was not found")
            extension = IMAGE_EXTENSIONS.get(artifact.content_type)
            if extension is None:
                raise ReductoOcrError(
                    f"Raster image {ref.artifact_id} has unsupported content type "
                    f"{artifact.content_type!r}"
                )
            stream = await self._storage.load(
                bucket=artifact.bucket, path=artifact.object_key
            )
            try:
                content = stream.read(MAX_SOURCE_BYTES + 1)
            finally:
                stream.close()
        except ReductoOcrError:
            raise
        except Exception as exc:
            raise ReductoOcrError(
                f"Reducto OCR could not read raster image {ref.artifact_id}"
            ) from exc
        if len(content) > MAX_SOURCE_BYTES:
            raise ReductoOcrError(
                f"Raster image {ref.artifact_id} exceeds the "
                f"{MAX_SOURCE_BYTES}-byte source limit"
            )
        if (
            artifact.sha256 is not None
            and sha256(content).hexdigest() != artifact.sha256
        ):
            raise ReductoOcrError(
                f"Raster image {ref.artifact_id} SHA-256 does not match"
            )
        upload = await client.upload(
            file=(f"document{extension}", content, artifact.content_type),
            extension=extension,
        )
        return upload.file_id

    async def _download_chunks(self, url: str) -> list[ParseChunk]:
        # A separate client: this host is the provider's storage and must never see
        # the API key. Non-JSON and off-contract bodies raise ValueError for `run`.
        if not url.startswith("https://"):
            raise ReductoOcrError("Reducto returned a result URL that is not HTTPS")
        body = bytearray()
        async with (
            httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
                transport=self._transport_factory(),
            ) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code != 200:
                raise ReductoOcrError(
                    f"Reducto result download returned HTTP {response.status_code}"
                )
            async for part in response.aiter_bytes():
                body.extend(part)
                if len(body) > MAX_RESULT_BYTES:
                    raise ReductoOcrError(
                        f"Reducto result download exceeded {MAX_RESULT_BYTES} bytes"
                    )
        payload: object = json.loads(bytes(body))
        # The document is the chunk array, or an object carrying it under `chunks`.
        if isinstance(payload, dict):
            payload = cast(dict[str, object], payload).get("chunks")
        return ParseChunkList.validate_python(payload)

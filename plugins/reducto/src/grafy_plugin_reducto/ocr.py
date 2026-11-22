import asyncio
import json
from collections.abc import Callable
from typing import Annotated, Any, ClassVar, Final, Literal, cast, final, override

import httpx
from pydantic import Field, SecretStr, model_validator
from reducto import APIConnectionError, APIStatusError, AsyncReducto
from reducto.types import SettingsParam
from reducto.types.shared_params.page_range import PageRange

from grafy_core.artifact_contracts import MarkdownValue
from grafy_core.credential_verification import unsupported_credential_verifier
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import field_ui
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.egress import EgressRejectedError, PinnedPublicAddressTransport
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    UserFacingNodeError,
)
from grafy_core.ocr_contracts import OcrFeature, OcrReader, OcrResult
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.table_contracts import (
    Table,
    TableColumn,
    TableValue,
    TableValueType,
)

import grafy_workbench.table.plugin as _table_plugin
import grafy_workbench.text.nodes as _text_nodes
from grafy_plugin_reducto.declaration import REDUCTO
from grafy_plugin_reducto.response import ParseChunk, ParseChunkList

_ = (_table_plugin.__name__, _text_nodes.__name__)  # notes classes before these ports

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
        title="Model",
        default="r-1",
        description=(
            "Reducto Parse model. Always sent, so a change to the provider's default "
            "cannot move existing graphs. r-1-mini does not accept spreadsheets."
        ),
        json_schema_extra=field_ui(
            enum_labels={"r-1": "Standard", "r-1-mini": "Faster (no spreadsheets)"}
        ),
    )
    page_start: int | None = Field(
        title="First page",
        json_schema_extra=field_ui(advanced=True),
        default=None,
        ge=1,
        description="First page to process, 1-indexed. Empty processes from page 1.",
    )
    page_end: int | None = Field(
        title="Last page",
        json_schema_extra=field_ui(advanced=True),
        default=None,
        ge=1,
        description="Last page to process, 1-indexed. Empty processes to the end.",
    )
    table_format: Literal["md", "html"] = Field(
        title="Table format",
        json_schema_extra=field_ui(
            advanced=True, enum_labels={"md": "Markdown", "html": "HTML"}
        ),
        default="md",
        description="Render tables as Markdown, or HTML for tables with merged cells.",
    )
    timeout_s: int = Field(
        title="Time limit (seconds)",
        json_schema_extra=field_ui(advanced=True),
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
            raise ValueError("The last page cannot come before the first page.")
        return self


class ReductoOcrInput(NodeInput):
    document_url: Annotated[
        str | None,
        Field(
            title="Document link",
            description=(
                "Web address of a document Reducto can fetch, including a signed "
                "link. Leave empty when a scan or PDF is connected."
            ),
        ),
    ] = None
    image: Annotated[
        RasterImage | PdfFile | None,
        Field(
            title="Scan or PDF",
            description=(
                "One scanned page or a PDF. Leave empty when a document link "
                "is connected."
            ),
        ),
    ] = None


class ReductoOcrOutput(NodeOutput):
    markdown: Annotated[
        MarkdownValue,
        Field(
            title="Transcription",
            description="The reading, with pages kept in order.",
        ),
    ]
    blocks: Annotated[
        Table,
        Field(
            title="Text blocks",
            description=(
                "One row per piece the reader found: page, kind of region, text, "
                "and box."
            ),
        ),
    ]


class ReductoOcrError(UserFacingNodeError):
    pass


def build_parse_output(chunks: list[ParseChunk]) -> OcrResult:
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
    return OcrResult(
        markdown=MarkdownValue(markdown="\n\n".join(chunk.content for chunk in chunks)),
        blocks=Table(
            columns=[
                TableColumn(id=name, title=name, value_type=value_type)
                for name, value_type in BLOCK_COLUMNS
            ],
            rows=rows,
        ),
        regions=None,
    )


class ReductoReader(OcrReader):
    features: ClassVar[frozenset[OcrFeature]] = frozenset({OcrFeature.BLOCKS})
    title: ClassVar[str] = "Reducto"

    def __init__(
        self,
        *,
        config: ReductoOcrConfig,
        api_key: SecretStr,
        transport_factory: Callable[[], httpx.AsyncBaseTransport],
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._transport_factory = transport_factory

    async def read(self, document: RasterImage | PdfFile) -> OcrResult:
        return await _run_parse(
            config=self._config,
            api_key=self._api_key,
            document_url=None,
            image=document,
            transport_factory=self._transport_factory,
            node_id=None,
        )

    async def read_document_url(self, document_url: str) -> OcrResult:
        return await _run_parse(
            config=self._config,
            api_key=self._api_key,
            document_url=document_url,
            image=None,
            transport_factory=self._transport_factory,
            node_id=None,
        )


class ReductoProviderInput(NodeInput):
    pass


class ReductoProviderOutput(NodeOutput):
    reader: Annotated[
        ReductoReader,
        Field(title="OCR reader", description="Reads a scan or PDF with Reducto."),
    ]


#: The credential this node reads with `context.secrets.require(API_KEY.name)`.
API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    description="Write-only bearer credential for the Reducto platform API.",
    config_dependencies=(),
    provider_kind="reducto",
    verifier=unsupported_credential_verifier(
        "Reducto has no free verification endpoint; key will be checked on first run."
    ),
)


def build_reducto_ocr_node(context: PluginRuntimeContext) -> "ReductoOcrNode":
    del context
    return ReductoOcrNode()


def build_reducto_ocr_provider_node(
    context: PluginRuntimeContext,
) -> "ReductoOcrProviderNode":
    del context
    return ReductoOcrProviderNode()


async def _run_parse(
    *,
    config: ReductoOcrConfig,
    api_key: SecretStr,
    document_url: str | None,
    image: RasterImage | PdfFile | None,
    transport_factory: Callable[[], httpx.AsyncBaseTransport],
    node_id: str | None,
) -> OcrResult:
    if (document_url is None) == (image is None):
        raise ReductoOcrError(
            "Connect either a document link or a page image, not both, and not neither."
        )
    # Also keeps the provider's own reducto:// and jobid:// inputs out of graphs.
    # The URL is never quoted: a presigned one carries its signature.
    if document_url is not None and not document_url.startswith("https://"):
        raise ReductoOcrError("The document link has to start with https://.")

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
                    transport=transport_factory(),
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
                if image is not None:
                    source = await _upload_image(client, image)
                else:
                    source = cast(str, document_url)
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
                    chunks = await _download_chunks(
                        result["url"], transport_factory=transport_factory
                    )
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
        label = (
            "Reducto OCR failed"
            if node_id is None
            else (f"Reducto OCR failed for node {node_id!r}")
        )
        raise ReductoOcrError(label) from None


async def _upload_image(client: AsyncReducto, image: RasterImage | PdfFile) -> str:
    label = image.filename or "this file"
    if isinstance(image, PdfFile):
        extension = ".pdf"
        content_type = PdfFile.media_type
    else:
        extension = IMAGE_EXTENSIONS.get(image.content_type)
        content_type = image.content_type
        if extension is None:
            raise ReductoOcrError(
                f"{label} has unsupported content type {image.content_type!r}"
            )
    try:
        content = await image.read(max_bytes=MAX_SOURCE_BYTES)
    except ValueError as exc:
        if "over the limit" in str(exc):
            raise ReductoOcrError(
                f"{label} exceeds the {MAX_SOURCE_BYTES}-byte source limit"
            ) from exc
        raise ReductoOcrError(f"Reducto OCR could not read {label}") from exc
    except ReductoOcrError:
        raise
    except Exception as exc:
        raise ReductoOcrError(f"Reducto OCR could not read {label}") from exc
    upload = await client.upload(
        file=(f"document{extension}", content, content_type),
        extension=extension,
    )
    return upload.file_id


async def _download_chunks(
    url: str,
    *,
    transport_factory: Callable[[], httpx.AsyncBaseTransport],
) -> list[ParseChunk]:
    # A separate client: this host is the provider's storage and must never see
    # the API key. Non-JSON and off-contract bodies raise ValueError for `run`.
    if not url.startswith("https://"):
        raise ReductoOcrError("Reducto returned a result URL that is not HTTPS")
    body = bytearray()
    async with (
        httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            transport=transport_factory(),
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


@REDUCTO.node(
    operator_id="reducto.ocr.provider",
    version=1,
    title="Reducto",
    factory=build_reducto_ocr_provider_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(API_KEY,),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=(REDUCTO_BASE_URL,),
        dynamic_destinations=True,
    ),
)
@final
class ReductoOcrProviderNode(
    Node[ReductoOcrConfig, ReductoProviderInput, ReductoProviderOutput]
):
    """Supplies a Reducto OCR reader. Connect it to an OCR node."""

    def __init__(
        self,
        *,
        transport_factory: Callable[
            [], httpx.AsyncBaseTransport
        ] = PinnedPublicAddressTransport,
    ) -> None:
        self._transport_factory = transport_factory

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ReductoOcrConfig,
        _inputs: ReductoProviderInput,
        /,
    ) -> ReductoProviderOutput:
        api_key = await context.secrets.require(API_KEY.name)
        return ReductoProviderOutput(
            reader=ReductoReader(
                config=config,
                api_key=api_key,
                transport_factory=self._transport_factory,
            )
        )


@REDUCTO.node(
    operator_id="reducto.ocr.process",
    version=1,
    title="Read with Reducto",
    factory=build_reducto_ocr_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(API_KEY,),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=(REDUCTO_BASE_URL,),
        # A large result comes back as a presigned URL on the provider's storage.
        dynamic_destinations=True,
    ),
)
@final
class ReductoOcrNode(Node[ReductoOcrConfig, ReductoOcrInput, ReductoOcrOutput]):
    """Reads a PDF or a scanned page into text. You need a Reducto key."""

    def __init__(
        self,
        *,
        transport_factory: Callable[
            [], httpx.AsyncBaseTransport
        ] = PinnedPublicAddressTransport,
    ) -> None:
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
                "Connect either a document link or a page image, not both, and "
                "not neither."
            )
        if inputs.document_url is not None and not inputs.document_url.startswith(
            "https://"
        ):
            raise ReductoOcrError("The document link has to start with https://.")
        api_key = await context.secrets.require(API_KEY.name)
        reader = ReductoReader(
            config=config,
            api_key=api_key,
            transport_factory=self._transport_factory,
        )
        if inputs.document_url is not None:
            result = await reader.read_document_url(inputs.document_url)
        else:
            assert inputs.image is not None
            result = await reader.read(inputs.image)
        if result.blocks is None:
            raise ReductoOcrError("Reducto OCR did not return text blocks")
        return ReductoOcrOutput(markdown=result.markdown, blocks=result.blocks)

import re
from ipaddress import ip_address
from typing import Annotated, Literal, Protocol, final, override
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import ArtifactRef, NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.schema_contracts import JSON_SCHEMA

from grafy_plugin_mistral.artifacts import OCR_DOCUMENT, OcrDocumentPayload
from grafy_plugin_mistral.declaration import MISTRAL


_PAGES = re.compile(r"^(?:\d+(?:-\d+)?)(?:,\d+(?:-\d+)?)*$")
_URL = TypeAdapter(AnyHttpUrl)

TableFormat = Literal["markdown", "html"]
ConfidenceGranularity = Literal["word", "page", "block"]


class MistralOcrConfig(NodeConfig):
    base_url: StrictStr = Field(
        default="https://api.mistral.ai",
        min_length=1,
        description="Mistral API origin. The SDK appends /v1/ocr.",
    )
    model: StrictStr = Field(
        default="mistral-ocr-latest",
        min_length=1,
        description="OCR model identifier.",
    )
    document_name: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Optional document name sent with an HTTPS document URL.",
    )
    pages: StrictStr | None = Field(
        default=None,
        description=(
            "Pages to process, as comma-separated indexes and ranges such as "
            "0,2-4. Indexes start at 0. Empty processes every page."
        ),
    )
    include_image_base64: bool = Field(
        default=False,
        description="Persist base64 bytes for images extracted from the document.",
    )
    image_limit: int | None = Field(
        default=None,
        ge=0,
        le=1_000,
        description="Maximum number of images to extract.",
    )
    image_min_size: int | None = Field(
        default=None,
        ge=0,
        le=10_000,
        description="Minimum height and width, in pixels, of an extracted image.",
    )
    table_format: TableFormat | None = Field(
        default=None,
        description="Render extracted tables as Markdown or HTML.",
    )
    extract_header: bool = Field(
        default=False,
        description="Move page headers out of the markdown into the header field.",
    )
    extract_footer: bool = Field(
        default=False,
        description="Move page footers out of the markdown into the footer field.",
    )
    include_blocks: bool = Field(
        default=True,
        description="Include paragraph-level content blocks with bounding boxes.",
    )
    confidence_scores_granularity: ConfidenceGranularity | None = Field(
        default=None,
        description="Attach page, word, or block confidence scores.",
    )
    document_annotation_prompt: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=8_000,
        description=(
            "Prompt that guides document-level structured extraction. Requires "
            "a connected document annotation schema."
        ),
    )
    document_annotation_schema_name: StrictStr = Field(
        default="document_annotation",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Provider-facing name for the document annotation schema.",
    )
    bbox_annotation_schema_name: StrictStr = Field(
        default="bbox_annotation",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Provider-facing name for the image annotation schema.",
    )
    strict: bool = Field(
        default=True,
        description="Whether annotation schemas are strict JSON Schemas.",
    )
    timeout_ms: int = Field(
        default=120_000,
        ge=1_000,
        le=900_000,
        description="Maximum provider request time in milliseconds.",
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=5,
        description=(
            "Additional attempts after a timeout, connection failure, or "
            "retryable HTTP status. Keep at zero when a duplicate OCR call is "
            "unacceptable."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_public_http_url(
            value,
            label="base_url",
            allow_query=False,
            strip_trailing_slash=True,
        )

    @field_validator("document_name", "document_annotation_prompt")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip():
            raise ValueError("must not have surrounding whitespace")
        return value

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or _PAGES.fullmatch(value) is None:
            raise ValueError(
                "pages must be comma-separated indexes or ranges, such as 0,2-4"
            )
        for part in value.split(","):
            if "-" not in part:
                continue
            start_text, end_text = part.split("-", 1)
            if int(start_text) > int(end_text):
                raise ValueError(f"page range {part!r} has its end before its start")
        return value


class MistralOcrInput(NodeInput):
    document_url: Annotated[
        str | None,
        InPort(TEXT_VALUE),
        Field(
            description=(
                "HTTPS URL of a PDF, presentation, or other document Mistral "
                "OCR can fetch. Leave empty when a raster image is connected."
            ),
        ),
    ] = None
    image: Annotated[
        ArtifactRef | None,
        InPort(RASTER_IMAGE),
        Field(
            description=(
                "Raster image to recognize. Leave empty when a document URL "
                "is connected."
            ),
        ),
    ] = None
    document_annotation_schema: Annotated[
        str | None,
        InPort(JSON_SCHEMA),
        Field(
            title="Document annotation schema",
            description="Optional JSON Schema extracted from the whole document.",
        ),
    ] = None
    bbox_annotation_schema: Annotated[
        str | None,
        InPort(JSON_SCHEMA),
        Field(
            title="Image annotation schema",
            description=(
                "Optional JSON Schema extracted for each image in the document."
            ),
        ),
    ] = None


class MistralOcrOutput(NodeOutput):
    document: Annotated[
        OcrDocumentPayload,
        OutPort(OCR_DOCUMENT),
        Field(description="Recognized pages, tables, images, and annotations."),
    ]


class MistralOcrProvider(Protocol):
    async def process(
        self,
        *,
        document_url: str | None,
        image: ArtifactRef | None,
        document_annotation_schema: str | None,
        bbox_annotation_schema: str | None,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> OcrDocumentPayload: ...


class MistralOcrProviderError(RuntimeError):
    """A provider failure whose message is safe to show to graph users."""


class MistralOcrExecutionError(UserFacingNodeError):
    pass


def validate_public_http_url(
    value: str,
    *,
    label: str,
    allow_query: bool,
    strip_trailing_slash: bool,
) -> str:
    if value != value.strip():
        raise ValueError(f"{label} must not have surrounding whitespace")
    url = _URL.validate_python(value)
    if url.username is not None or url.password is not None:
        raise ValueError(f"{label} must not include user information")
    if not allow_query and url.query is not None:
        raise ValueError(f"{label} must not include a query")
    if url.fragment is not None:
        raise ValueError(f"{label} must not include a fragment")
    host = url.host
    if host is None:
        raise ValueError(f"{label} must include a host")
    if url.scheme == "http" and not _is_loopback(host):
        raise ValueError(
            f"{label} must use HTTPS unless it targets localhost or a loopback "
            "IP address"
        )
    rendered = str(url)
    if strip_trailing_slash:
        return rendered.rstrip("/")
    return rendered


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def build_mistral_ocr_node(context: PluginRuntimeContext) -> "MistralOcrNode":
    from grafy_plugin_mistral.ocr_sdk import MistralOcrSdkProvider

    return MistralOcrNode(
        provider=MistralOcrSdkProvider(
            uow=context.uow,
            storage=context.storage,
        ),
        node_secrets=context.node_secrets,
    )


@MISTRAL.node(
    operator_id="mistral.ocr.process",
    version=1,
    title="Mistral OCR",
    factory=build_mistral_ocr_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            description="Write-only bearer credential for the configured API origin.",
            config_dependencies=("base_url",),
        ),
    ),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
    ),
)
@final
class MistralOcrNode(Node[MistralOcrConfig, MistralOcrInput, MistralOcrOutput]):
    """Recognizes a document URL or raster image with Mistral OCR."""

    def __init__(
        self,
        *,
        provider: MistralOcrProvider,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._provider = provider
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: MistralOcrConfig,
        inputs: MistralOcrInput,
        /,
    ) -> MistralOcrOutput:
        if (inputs.document_url is None) == (inputs.image is None):
            raise MistralOcrExecutionError(
                "Mistral OCR requires exactly one of a document URL or a raster "
                f"image on node {context.node_id!r}"
            )
        if config.document_name is not None and inputs.document_url is None:
            raise MistralOcrExecutionError(
                "Mistral OCR document name applies only to a document URL on "
                f"node {context.node_id!r}"
            )
        if (
            config.document_annotation_prompt is not None
            and inputs.document_annotation_schema is None
        ):
            raise MistralOcrExecutionError(
                "Mistral OCR document annotation prompt requires a document "
                f"annotation schema on node {context.node_id!r}"
            )

        try:
            api_key = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                graph_id=context.secret_graph_id,
                graph_revision=context.secret_graph_revision,
                node_id=context.node_id,
                name="api_key",
                dependencies={"base_url": config.base_url},
            )
        except Exception as exc:
            raise MistralOcrExecutionError(
                "Mistral OCR could not resolve its API key for node "
                f"{context.node_id!r}, model {config.model!r}, and base URL "
                f"{config.base_url!r}"
            ) from exc

        try:
            document = await self._provider.process(
                document_url=inputs.document_url,
                image=inputs.image,
                document_annotation_schema=inputs.document_annotation_schema,
                bbox_annotation_schema=inputs.bbox_annotation_schema,
                config=config,
                api_key=api_key,
                workspace_id=context.workspace_id,
            )
        except MistralOcrProviderError as exc:
            raise MistralOcrExecutionError(str(exc)) from exc
        except Exception as exc:
            raise MistralOcrExecutionError(
                "Mistral OCR failed for model "
                f"{config.model!r} and base URL {config.base_url!r}"
            ) from exc
        return MistralOcrOutput(document=document)

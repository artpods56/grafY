import base64
import logging
from ipaddress import ip_address
from typing import Annotated, Literal, Protocol, cast, final, override
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    TypeAdapter,
    model_validator,
)

from mistralai.client.models.ocrresponse import OCRResponse

from grafy_core.artifact_contracts import (
    RASTER_IMAGE,
    TEXT_VALUE,
    MARKDOWN,
    IMAGE_REGIONS,
    MarkdownValue,
    ImageRegion,
    ImageRegionSet,
    RasterImageContent,
    RasterImageContentType,
)
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValue,
    TableValueType,
)
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
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort

from grafy_plugin_mistral.declaration import MISTRAL
from grafy_plugin_mistral.response import OcrPage


_URL = TypeAdapter(AnyHttpUrl)
logger = logging.getLogger(__name__)
TableFormat = Literal["markdown", "html"]
ConfidenceGranularity = Literal["page", "block"]
_LEGACY_CONFIG_KEYS = frozenset(
    {
        "base_url",
        "model",
        "document_name",
        "pages",
        "include_image_base64",
        "image_limit",
        "image_min_size",
        "include_blocks",
        "document_annotation_prompt",
        "document_annotation_schema_name",
        "bbox_annotation_schema_name",
        "strict",
    }
)


class MistralOcrConfig(NodeConfig):
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
    confidence_scores_granularity: ConfidenceGranularity | None = Field(
        default=None,
        description="Attach page or block confidence scores.",
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

    @model_validator(mode="before")
    @classmethod
    def drop_legacy_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                key: item
                for key, item in cast(dict[str, object], value).items()
                if key not in _LEGACY_CONFIG_KEYS
            }
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


class MistralOcrOutput(NodeOutput):
    markdown: Annotated[
        MarkdownValue,
        OutPort(MARKDOWN),
        Field(description="Recognized document as Markdown, pages joined in order."),
    ]
    blocks: Annotated[
        Table,
        OutPort(TABLE_DATA),
        Field(
            description="One row per recognized block with its page, kind, box, text, and confidence."
        ),
    ]
    regions: Annotated[
        list[ImageRegionSet],
        OutPort(IMAGE_REGIONS),
        Field(
            description="One region set per page, in page pixel coordinates, for drawing boxes."
        ),
    ]
    figures: Annotated[
        list[RasterImageContent],
        OutPort(RASTER_IMAGE),
        Field(description="Figures cropped from the document, in page order."),
    ]


class MistralOcrProvider(Protocol):
    async def process(
        self,
        *,
        document_url: str | None,
        image: ArtifactRef | None,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> MistralOcrOutput: ...


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
            config_dependencies=(),
        ),
    ),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=("https://api.mistral.ai",),
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
        try:
            api_key = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                graph_id=context.secret_graph_id,
                graph_revision=context.secret_graph_revision,
                node_id=context.node_id,
                name="api_key",
                dependencies={},
            )
        except Exception as exc:
            raise MistralOcrExecutionError(
                "Mistral OCR could not resolve its API key for node "
                f"{context.node_id!r}"
            ) from exc

        try:
            document = await self._provider.process(
                document_url=inputs.document_url,
                image=inputs.image,
                config=config,
                api_key=api_key,
                workspace_id=context.workspace_id,
            )
        except MistralOcrProviderError as exc:
            raise MistralOcrExecutionError(str(exc)) from exc
        except Exception as exc:
            raise MistralOcrExecutionError(
                f"Mistral OCR failed for node {context.node_id!r}"
            ) from exc
        return document


def _normalise_box(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    """Clamp negative corners and swap inverted ones into top-left order."""
    left, top, right, bottom = max(0, x0), max(0, y0), max(0, x1), max(0, y1)
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return left, top, right, bottom


def _page_regions(page: OcrPage) -> ImageRegionSet | None:
    dims = page.dimensions
    if dims is None or dims.width == 0 or dims.height == 0:
        return None

    boxes: list[tuple[int, int, int, int, str, str | None]] = []
    if page.blocks is not None:
        for block in page.blocks:
            text_label = " ".join(block.content.split())
            if len(text_label) > 120:
                text_label = text_label[:120] + "…"
            label: str | None = text_label or None
            if block.type == "image":
                label = block.image_id
            elif block.type == "table" and block.table_id is not None:
                label = block.table_id
            boxes.append(
                (
                    block.top_left_x,
                    block.top_left_y,
                    block.bottom_right_x,
                    block.bottom_right_y,
                    block.type,
                    label,
                )
            )
    else:
        for image in page.images:
            if (
                image.top_left_x is None
                or image.top_left_y is None
                or image.bottom_right_x is None
                or image.bottom_right_y is None
            ):
                continue
            boxes.append(
                (
                    image.top_left_x,
                    image.top_left_y,
                    image.bottom_right_x,
                    image.bottom_right_y,
                    "image",
                    image.id,
                )
            )

    regions: list[ImageRegion] = []
    for x0, y0, x1, y1, kind, label in boxes:
        left, top, right, bottom = _normalise_box(x0, y0, x1, y1)
        regions.append(
            ImageRegion(x0=left, y0=top, x1=right, y1=bottom, kind=kind, label=label)
        )
    return ImageRegionSet(
        width=dims.width, height=dims.height, page_index=page.index, regions=regions
    )


_BLOCK_COLUMNS = (
    ("page", TableValueType.INTEGER),
    ("index", TableValueType.INTEGER),
    ("kind", TableValueType.TEXT),
    ("x0", TableValueType.INTEGER),
    ("y0", TableValueType.INTEGER),
    ("x1", TableValueType.INTEGER),
    ("y1", TableValueType.INTEGER),
    ("text", TableValueType.TEXT),
    ("ref", TableValueType.TEXT),
    ("confidence", TableValueType.NUMBER),
    ("min_confidence", TableValueType.NUMBER),
    ("page_confidence", TableValueType.NUMBER),
)
_FIGURE_TYPES: dict[str, RasterImageContentType] = {
    "image/jpeg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
    "image/tiff": "image/tiff",
    "image/bmp": "image/bmp",
}


def build_ocr_output(
    response: OCRResponse, config: MistralOcrConfig
) -> MistralOcrOutput:
    markdown_pages: list[str] = []
    rows: list[dict[str, TableValue]] = []
    regions: list[ImageRegionSet] = []
    figures: list[RasterImageContent] = []
    for sdk_page in response.pages:
        page = OcrPage.model_validate(sdk_page.model_dump(mode="json", by_alias=True))
        tables = {table.id: table.content for table in page.tables or []}
        markdown = page.markdown
        for table_id, content in tables.items():
            markdown = markdown.replace(f"[{table_id}]({table_id})", content)
        markdown_pages.append(markdown)
        page_regions = _page_regions(page)
        if page_regions is None:
            logger.warning(
                "Skipping regions for OCR page %s because it reports no pixel dimensions",
                page.index,
            )
        else:
            regions.append(page_regions)
        for index, block in enumerate(page.blocks or []):
            box = _normalise_box(
                block.top_left_x,
                block.top_left_y,
                block.bottom_right_x,
                block.bottom_right_y,
            )
            ref = None
            text = block.content
            if block.type == "image":
                ref = block.image_id
                text = block.image_id
            elif block.type == "table":
                ref = block.table_id
                text = tables.get(ref, text) if ref is not None else text
            scores = (
                block.confidence_scores
                if config.confidence_scores_granularity == "block"
                else None
            )
            page_scores = (
                page.confidence_scores
                if config.confidence_scores_granularity == "page"
                else None
            )
            rows.append(
                {
                    "page": page.index,
                    "index": index,
                    "kind": block.type,
                    "x0": box[0],
                    "y0": box[1],
                    "x1": box[2],
                    "y1": box[3],
                    "text": text,
                    "ref": ref,
                    "confidence": scores.average_content_confidence_score
                    if scores is not None
                    else None,
                    "min_confidence": scores.minimum_content_confidence_score
                    if scores is not None
                    else None,
                    "page_confidence": page_scores.average_page_confidence_score
                    if page_scores is not None
                    else None,
                }
            )
        for image in page.images:
            encoded = image.image_base64
            if not encoded:
                continue
            content_type = None
            if encoded.startswith("data:"):
                header, separator, encoded = encoded.partition(",")
                if not separator or not header.endswith(";base64"):
                    raise MistralOcrProviderError(
                        f"OCR figure {image.id!r} on page {page.index} has an invalid base64 data URL"
                    )
                content_type = _FIGURE_TYPES.get(header[5:-7].lower())
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise MistralOcrProviderError(
                    f"OCR figure {image.id!r} on page {page.index} has invalid base64"
                ) from exc
            if content_type is None:
                if content.startswith(b"\x89PNG"):
                    content_type = "image/png"
                elif content.startswith(b"\xff\xd8"):
                    content_type = "image/jpeg"
                elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                    content_type = "image/webp"
            if content_type is None or not content:
                logger.warning(
                    "Skipping OCR figure %r on page %s with unknown or empty image content",
                    image.id,
                    page.index,
                )
                continue
            figures.append(
                RasterImageContent(
                    content=content, content_type=content_type, filename=image.id
                )
            )
    logger.info(
        "Mistral OCR processed %s pages, document size %s bytes",
        response.usage_info.pages_processed,
        response.usage_info.doc_size_bytes,
    )
    return MistralOcrOutput(
        markdown=MarkdownValue(markdown="\n\n".join(markdown_pages)),
        blocks=Table(
            columns=[
                TableColumn(id=name, title=name, value_type=value_type)
                for name, value_type in _BLOCK_COLUMNS
            ],
            rows=rows,
        ),
        regions=regions,
        figures=figures,
    )

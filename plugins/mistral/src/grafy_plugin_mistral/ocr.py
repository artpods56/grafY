import logging
from collections.abc import Mapping
from typing import Annotated, ClassVar, Literal, Protocol, final, override
from uuid import UUID

import httpx
from grafy_core.artifact_contracts import (
    ImagePage,
    ImageRegion,
    ImageRegionSet,
    MarkdownValue,
)
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import field_ui
from grafy_core.contracts.ocr import DocumentOcr, DocumentOcrFeature, DocumentOcrResult
from grafy_core.credential_verification import verify_http_credential
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.domain.credentials import CredentialVerificationResult
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    UserFacingNodeError,
)
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
from mistralai.client.models.ocrresponse import OCRResponse
from pydantic import (
    Field,
    SecretStr,
)

from grafy_plugin_mistral.declaration import MISTRAL
from grafy_plugin_mistral.response import OcrPage

logger = logging.getLogger(__name__)
TableFormat = Literal["markdown", "html"]
ConfidenceGranularity = Literal["page", "block"]


class MistralOcrConfig(NodeConfig):
    table_format: TableFormat | None = Field(
        title="Table format",
        json_schema_extra=field_ui(
            advanced=True, enum_labels={"markdown": "Markdown", "html": "HTML"}
        ),
        default=None,
        description="Render extracted tables as Markdown or HTML.",
    )
    extract_header: bool = Field(
        title="Separate headers",
        json_schema_extra=field_ui(advanced=True),
        default=False,
        description="Move page headers out of the markdown into the header field.",
    )
    extract_footer: bool = Field(
        title="Separate footers",
        json_schema_extra=field_ui(advanced=True),
        default=False,
        description="Move page footers out of the markdown into the footer field.",
    )
    confidence_scores_granularity: ConfidenceGranularity | None = Field(
        title="Confidence detail",
        json_schema_extra=field_ui(
            advanced=True, enum_labels={"page": "Per page", "block": "Per region"}
        ),
        default=None,
        description="Attach page or block confidence scores.",
    )
    timeout_ms: int = Field(
        title="Time limit (ms)",
        json_schema_extra=field_ui(advanced=True),
        default=120_000,
        ge=1_000,
        le=900_000,
        description="Maximum provider request time in milliseconds.",
    )
    max_retries: int = Field(
        title="Max retries",
        json_schema_extra=field_ui(advanced=True),
        default=0,
        ge=0,
        le=5,
        description=(
            "Additional attempts after a timeout, connection failure, or "
            "retryable HTTP status. Keep at zero when a duplicate OCR call is "
            "unacceptable."
        ),
    )


class MistralOcrProvider(Protocol):
    async def process(
        self,
        *,
        image: RasterImage | PdfFile,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> DocumentOcrResult: ...


class MistralOcrProviderError(UserFacingNodeError):
    """A provider failure whose message is safe to show to graph users."""


class MistralReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset(
        {DocumentOcrFeature.BLOCKS, DocumentOcrFeature.REGIONS}
    )

    def __init__(
        self,
        *,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
        provider: MistralOcrProvider,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._provider = provider

    async def read(self, document: RasterImage | PdfFile) -> DocumentOcrResult:
        return await self._provider.process(
            image=document,
            config=self._config,
            api_key=self._api_key,
            workspace_id=self._workspace_id,
        )


class MistralProviderInput(NodeInput):
    pass


class MistralProviderOutput(NodeOutput):
    engine: Annotated[
        MistralReader,
        Field(
            title="Document OCR engine",
            description="Reads a scan or PDF with Mistral OCR.",
        ),
    ]


async def _verify_api_key(
    key: SecretStr, config: Mapping[str, JsonValue], client: httpx.AsyncClient
) -> CredentialVerificationResult:
    return await verify_http_credential(
        client,
        "https://api.mistral.ai/v1/models",
        f"Bearer {key.get_secret_value()}",
        message="Verified Mistral key.",
    )


#: The credential this node reads with `context.secrets.require(API_KEY.name)`.
API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    description="Write-only bearer credential for the configured API origin.",
    config_dependencies=(),
    provider_kind="mistral",
    verifier=_verify_api_key,
)


def build_mistral_ocr_provider_node(
    context: PluginRuntimeContext,
) -> "MistralOcrProviderNode":
    from grafy_plugin_mistral.ocr_sdk import MistralOcrSdkProvider

    del context
    return MistralOcrProviderNode(provider=MistralOcrSdkProvider())


@MISTRAL.node(
    operator_id="mistral.ocr.provider",
    version=1,
    title="Mistral OCR",
    factory=build_mistral_ocr_provider_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(API_KEY,),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=("https://api.mistral.ai",),
    ),
)
@final
class MistralOcrProviderNode(
    Node[MistralOcrConfig, MistralProviderInput, MistralProviderOutput]
):
    """Supplies a Mistral OCR reader. Connect it to an OCR node."""

    def __init__(self, *, provider: MistralOcrProvider) -> None:
        self._provider = provider

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: MistralOcrConfig,
        _inputs: MistralProviderInput,
        /,
    ) -> MistralProviderOutput:
        api_key = await context.secrets.require(API_KEY.name)
        return MistralProviderOutput(
            engine=MistralReader(
                config=config,
                api_key=api_key,
                workspace_id=context.workspace_id,
                provider=self._provider,
            )
        )


def _normalise_box(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    """Clamp negative corners and swap inverted ones into top-left order."""
    left, top, right, bottom = max(0, x0), max(0, y0), max(0, x1), max(0, y1)
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return left, top, right, bottom


def _page_regions(page: OcrPage) -> list[ImageRegion]:
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
            ImageRegion(
                page=page.index,
                x0=left,
                y0=top,
                x1=right,
                y1=bottom,
                kind=kind,
                label=label,
            )
        )
    return regions


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


def build_ocr_output(
    response: OCRResponse, config: MistralOcrConfig
) -> DocumentOcrResult:
    markdown_pages: list[str] = []
    rows: list[dict[str, TableValue]] = []
    pages: list[ImagePage] = []
    regions: list[ImageRegion] = []
    for sdk_page in response.pages:
        page = OcrPage.model_validate(sdk_page.model_dump(mode="json", by_alias=True))
        tables = {table.id: table.content for table in page.tables or []}
        markdown = page.markdown
        for table_id, content in tables.items():
            markdown = markdown.replace(f"[{table_id}]({table_id})", content)
        markdown_pages.append(markdown)
        dims = page.dimensions
        if dims is None or dims.width <= 0 or dims.height <= 0:
            raise MistralOcrProviderError(
                f"OCR page {page.index} reports no pixel dimensions"
            )
        pages.append(ImagePage(index=page.index, width=dims.width, height=dims.height))
        regions.extend(_page_regions(page))
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
    logger.info(
        "Mistral OCR processed %s pages, document size %s bytes",
        response.usage_info.pages_processed,
        response.usage_info.doc_size_bytes,
    )
    return DocumentOcrResult(
        markdown=MarkdownValue(markdown="\n\n".join(markdown_pages)),
        blocks=Table(
            columns=[
                TableColumn(id=name, title=name, value_type=value_type)
                for name, value_type in _BLOCK_COLUMNS
            ],
            rows=rows,
        ),
        regions=ImageRegionSet(pages=pages, regions=regions),
    )

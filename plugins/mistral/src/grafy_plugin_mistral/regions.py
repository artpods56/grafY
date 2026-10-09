from typing import Annotated, Literal, final, get_args, override

from pydantic import Field, StrictStr, field_validator

from grafy_core.artifact_contracts import IMAGE_REGIONS, ImageRegion, ImageRegionSet
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)

from grafy_plugin_mistral.artifacts import OCR_DOCUMENT, OcrDocumentPayload
from grafy_plugin_mistral.declaration import MISTRAL


OcrRegionKind = Literal[
    "aside_text",
    "caption",
    "code",
    "equation",
    "footer",
    "header",
    "image",
    "list",
    "references",
    "signature",
    "table",
    "text",
    "title",
]
_KINDS: frozenset[str] = frozenset(get_args(OcrRegionKind))
_LABEL_CHARS = 120


class OcrRegionsConfig(NodeConfig):
    page_index: int = Field(
        default=0,
        ge=0,
        description="Zero-based page index, matching the OCR page index (not list position).",
    )
    kinds: StrictStr | None = Field(
        default=None,
        description="Comma-separated region kinds to keep, such as table,title. Empty keeps every kind.",
    )

    @field_validator("kinds")
    @classmethod
    def validate_kinds(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts: list[str] = []
        for part in value.split(","):
            part = part.strip()
            if part not in _KINDS:
                raise ValueError(
                    f"unknown region kind {part!r}; expected one of {', '.join(sorted(_KINDS))}"
                )
            if part not in parts:
                parts.append(part)
        return ",".join(parts)


class OcrRegionsInput(NodeInput):
    document: Annotated[
        OcrDocumentPayload,
        InPort(OCR_DOCUMENT),
        Field(description="Mistral OCR result to read boxes from."),
    ]


class OcrRegionsOutput(NodeOutput):
    regions: Annotated[
        ImageRegionSet,
        OutPort(IMAGE_REGIONS),
        Field(description="Boxes for the selected page in its pixel coordinates."),
    ]


class OcrRegionsError(UserFacingNodeError):
    pass


def extract_regions(
    document: OcrDocumentPayload, *, page_index: int, kinds: frozenset[str] | None
) -> ImageRegionSet:
    page = next((page for page in document.pages if page.index == page_index), None)
    if page is None:
        raise OcrRegionsError(
            f"OCR document has no page {page_index}; available pages: "
            f"{', '.join(str(p.index) for p in document.pages)}"
        )
    dims = page.dimensions
    if dims is None or dims.width == 0 or dims.height == 0:
        raise OcrRegionsError(
            f"OCR page {page_index} has no pixel dimensions, so its boxes cannot be placed"
        )

    boxes: list[tuple[int, int, int, int, str, str | None]] = []
    if page.blocks is not None:
        for block in page.blocks:
            text_label = " ".join(block.content.split())
            if len(text_label) > _LABEL_CHARS:
                text_label = text_label[:_LABEL_CHARS] + "…"
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
        if kinds is not None and kind not in kinds:
            continue
        x0, y0, x1, y1 = max(0, x0), max(0, y0), max(0, x1), max(0, y1)
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        regions.append(ImageRegion(x0=x0, y0=y0, x1=x1, y1=y1, kind=kind, label=label))
    return ImageRegionSet(
        width=dims.width, height=dims.height, page_index=page.index, regions=regions
    )


@MISTRAL.node(
    operator_id="mistral.ocr.regions",
    version=1,
    title="OCR regions",
    factory=lambda context: OcrRegionsNode(),
)
@final
class OcrRegionsNode(Node[OcrRegionsConfig, OcrRegionsInput, OcrRegionsOutput]):
    """Extracts one page's bounding boxes from a Mistral OCR document."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: OcrRegionsConfig,
        inputs: OcrRegionsInput,
        /,
    ) -> OcrRegionsOutput:
        kinds = frozenset(config.kinds.split(",")) if config.kinds is not None else None
        return OcrRegionsOutput(
            regions=extract_regions(
                inputs.document, page_index=config.page_index, kinds=kinds
            )
        )

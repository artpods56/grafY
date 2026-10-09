import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from grafy_core.artifact_contracts import IMAGE_REGIONS, ImageRegion
from grafy_core.nodes import NodeExecutionContext
from grafy_plugin_mistral.artifacts import (
    OCR_DOCUMENT,
    OcrDocumentPayload,
    OcrImage,
    OcrImageBlock,
    OcrPage,
    OcrPageDimensions,
    OcrTableBlock,
    OcrTextBlock,
    OcrTitleBlock,
)
from grafy_plugin_mistral.regions import (
    OcrRegionsConfig,
    OcrRegionsError,
    OcrRegionsInput,
    OcrRegionsNode,
    OcrRegionsOutput,
    extract_regions,
)


@pytest.fixture
def document() -> OcrDocumentPayload:
    return OcrDocumentPayload(
        markdown="page",
        model="mistral-ocr-latest",
        base_url="https://api.mistral.ai",
        document_kind="image_url",
        pages_processed=1,
        include_image_base64=False,
        include_blocks=True,
        pages=[
            OcrPage(
                index=0,
                markdown="page",
                images=[],
                dimensions=OcrPageDimensions(dpi=300, width=600, height=800),
                blocks=[
                    OcrTitleBlock(
                        type="title",
                        top_left_x=1,
                        top_left_y=2,
                        bottom_right_x=30,
                        bottom_right_y=40,
                        content="  A \n title  ",
                    ),
                    OcrImageBlock(
                        type="image",
                        top_left_x=3,
                        top_left_y=4,
                        bottom_right_x=50,
                        bottom_right_y=60,
                        content="ignored",
                        image_id="image-1",
                    ),
                    OcrTableBlock(
                        type="table",
                        top_left_x=5,
                        top_left_y=6,
                        bottom_right_x=70,
                        bottom_right_y=80,
                        content="ignored",
                        table_id="table-1",
                    ),
                    OcrTableBlock(
                        type="table",
                        top_left_x=5,
                        top_left_y=6,
                        bottom_right_x=70,
                        bottom_right_y=80,
                        content=" fallback  table ",
                    ),
                    OcrTextBlock(
                        type="text",
                        top_left_x=7,
                        top_left_y=8,
                        bottom_right_x=90,
                        bottom_right_y=100,
                        content="x" * 121,
                    ),
                    OcrTextBlock(
                        type="text",
                        top_left_x=7,
                        top_left_y=8,
                        bottom_right_x=90,
                        bottom_right_y=100,
                        content=" \n ",
                    ),
                ],
            )
        ],
    )


def test_blocks_preserve_order_labels_and_pixel_space(
    document: OcrDocumentPayload,
) -> None:
    result = extract_regions(document, page_index=0, kinds=None)
    assert (result.width, result.height, result.page_index) == (600, 800, 0)
    assert [(r.kind, r.label) for r in result.regions] == [
        ("title", "A title"),
        ("image", "image-1"),
        ("table", "table-1"),
        ("table", "fallback table"),
        ("text", "x" * 120 + "…"),
        ("text", None),
    ]
    assert result.regions[0] == ImageRegion(
        x0=1, y0=2, x1=30, y1=40, kind="title", label="A title"
    )


def test_images_fallback_skips_each_missing_coordinate(
    document: OcrDocumentPayload,
) -> None:
    page = document.pages[0]
    page.blocks = None
    page.images = [
        OcrImage(
            id="complete",
            top_left_x=1,
            top_left_y=2,
            bottom_right_x=3,
            bottom_right_y=4,
        )
    ]
    for missing in ("top_left_x", "top_left_y", "bottom_right_x", "bottom_right_y"):
        image = page.images[0].model_copy(update={missing: None})
        page.images.append(image)
    result = extract_regions(document, page_index=0, kinds=None)
    assert result.regions == [
        ImageRegion(x0=1, y0=2, x1=3, y1=4, kind="image", label="complete")
    ]
    page.blocks = []
    assert extract_regions(document, page_index=0, kinds=None).regions == []


def test_kinds_filter(document: OcrDocumentPayload) -> None:
    result = extract_regions(
        document, page_index=0, kinds=frozenset({"table", "title"})
    )
    assert [r.kind for r in result.regions] == ["title", "table", "table"]
    assert extract_regions(document, page_index=0, kinds=frozenset()).regions == []


def test_page_selection_uses_index(document: OcrDocumentPayload) -> None:
    document.pages[0].index = 3
    document.pages.append(document.pages[0].model_copy(update={"index": 5}))
    assert extract_regions(document, page_index=5, kinds=None).page_index == 5
    with pytest.raises(
        OcrRegionsError, match="OCR document has no page 0; available pages: 3, 5"
    ):
        _ = extract_regions(document, page_index=0, kinds=None)


@pytest.mark.parametrize(
    "dimensions",
    [
        None,
        OcrPageDimensions(dpi=300, width=0, height=800),
        OcrPageDimensions(dpi=300, width=600, height=0),
    ],
)
def test_missing_dimensions(
    document: OcrDocumentPayload, dimensions: OcrPageDimensions | None
) -> None:
    document.pages[0].dimensions = dimensions
    with pytest.raises(
        OcrRegionsError,
        match="OCR page 0 has no pixel dimensions, so its boxes cannot be placed",
    ):
        _ = extract_regions(document, page_index=0, kinds=None)


@pytest.mark.parametrize("use_blocks", [True, False])
def test_coordinates_are_clamped_and_swapped(
    document: OcrDocumentPayload, use_blocks: bool
) -> None:
    page = document.pages[0]
    if use_blocks:
        page.blocks = [
            OcrTextBlock(
                type="text",
                top_left_x=20,
                top_left_y=30,
                bottom_right_x=-5,
                bottom_right_y=-10,
                content="box",
            )
        ]
    else:
        page.blocks = None
        page.images = [
            OcrImage(
                id="box",
                top_left_x=20,
                top_left_y=30,
                bottom_right_x=-5,
                bottom_right_y=-10,
            )
        ]
    region = extract_regions(document, page_index=0, kinds=None).regions[0]
    assert (region.x0, region.y0, region.x1, region.y1) == (0, 0, 20, 30)


def test_config_normalizes_and_deduplicates_kinds() -> None:
    assert OcrRegionsConfig(kinds="table, title,table").kinds == "table,title"
    assert OcrRegionsConfig().kinds is None


@pytest.mark.parametrize("kinds", ["table,bogus", "table,,title", "", " "])
def test_config_rejects_unknown_and_empty_kinds(kinds: str) -> None:
    with pytest.raises(ValidationError, match="unknown region kind"):
        _ = OcrRegionsConfig(kinds=kinds)


def test_node_run_returns_regions_output(document: OcrDocumentPayload) -> None:
    result = asyncio.run(
        OcrRegionsNode().run(
            NodeExecutionContext(workspace_id=uuid4(), node_id="regions-1"),
            OcrRegionsConfig(kinds="title"),
            OcrRegionsInput(document=document),
        )
    )
    assert isinstance(result, OcrRegionsOutput)
    assert result.regions.regions == [
        ImageRegion(x0=1, y0=2, x1=30, y1=40, kind="title", label="A title")
    ]
    assert OcrRegionsNode.input_contract.ports["document"].accepts == OCR_DOCUMENT.key
    assert OcrRegionsNode.output_contract.ports["regions"].produces == IMAGE_REGIONS.key

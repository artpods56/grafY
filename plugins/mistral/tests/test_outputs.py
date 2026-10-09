import pytest
from mistralai.client.models.ocrresponse import OCRResponse
from pydantic import ValidationError

from grafy_core.artifact_contracts import ImageRegion
from grafy_core.table_contracts import TableValueType
from grafy_plugin_mistral.ocr import (
    MistralOcrConfig,
    MistralOcrProviderError,
    build_ocr_output,
)


def response(pages: list[dict[str, object]]) -> OCRResponse:
    return OCRResponse.model_validate(
        {
            "model": "mistral-ocr-latest",
            "usage_info": {"pages_processed": len(pages)},
            "pages": pages,
        }
    )


def page(
    *, images: list[dict[str, object]] | None = None, **updates: object
) -> dict[str, object]:
    return {
        "index": 0,
        "markdown": "page",
        "images": [
            {
                "top_left_x": None,
                "top_left_y": None,
                "bottom_right_x": None,
                "bottom_right_y": None,
                **image,
            }
            for image in images or []
        ],
        "dimensions": {"dpi": 300, "width": 600, "height": 800},
        **updates,
    }


def block(kind: str = "text", **updates: object) -> dict[str, object]:
    return {
        "type": kind,
        "top_left_x": 1,
        "top_left_y": 2,
        "bottom_right_x": 30,
        "bottom_right_y": 40,
        "content": " A \n title ",
        **updates,
    }


def test_config_has_only_six_fields_and_discards_legacy_values() -> None:
    assert set(MistralOcrConfig.model_fields) == {
        "table_format",
        "extract_header",
        "extract_footer",
        "confidence_scores_granularity",
        "timeout_ms",
        "max_retries",
    }
    legacy = {
        key: {"invalid": "ignored"}
        for key in (
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
        )
    }
    assert MistralOcrConfig.model_validate(legacy) == MistralOcrConfig()
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _ = MistralOcrConfig.model_validate({"unrelated": True})
    with pytest.raises(ValidationError, match="literal_error"):
        _ = MistralOcrConfig.model_validate({"confidence_scores_granularity": "word"})


@pytest.mark.parametrize("table_format", ["html", "markdown"])
def test_markdown_inlines_tables_and_preserves_images(table_format: str) -> None:
    output = build_ocr_output(
        response(
            [
                page(
                    markdown="[tbl-0.html](tbl-0.html) ![img-0.jpeg](img-0.jpeg)",
                    tables=[
                        {"id": "tbl-0.html", "format": table_format, "content": "TABLE"}
                    ],
                ),
                page(index=3, markdown="second"),
            ]
        ),
        MistralOcrConfig.model_validate({"table_format": table_format}),
    )
    assert output.markdown.markdown == "TABLE ![img-0.jpeg](img-0.jpeg)\n\nsecond"
    assert [page.index for page in output.regions.pages] == [0, 3]


@pytest.mark.parametrize("granularity", [None, "block", "page"])
def test_blocks_columns_rows_and_confidence(granularity: str | None) -> None:
    output = build_ocr_output(
        response(
            [
                page(
                    blocks=[
                        block(
                            confidence_scores={
                                "average_content_confidence_score": 0.8,
                                "minimum_content_confidence_score": 0.5,
                            }
                        ),
                        block("table", table_id="tbl-0.html"),
                        block("image", image_id="img-0.jpeg"),
                    ],
                    tables=[
                        {
                            "id": "tbl-0.html",
                            "format": "html",
                            "content": "<table>10</table>",
                        }
                    ],
                    confidence_scores={
                        "average_page_confidence_score": 0.9,
                        "minimum_page_confidence_score": 0.4,
                    },
                )
            ]
        ),
        MistralOcrConfig.model_validate({"confidence_scores_granularity": granularity}),
    )
    assert [(c.id, c.title, c.value_type) for c in output.blocks.columns] == [
        ("page", "page", TableValueType.INTEGER),
        ("index", "index", TableValueType.INTEGER),
        ("kind", "kind", TableValueType.TEXT),
        ("x0", "x0", TableValueType.INTEGER),
        ("y0", "y0", TableValueType.INTEGER),
        ("x1", "x1", TableValueType.INTEGER),
        ("y1", "y1", TableValueType.INTEGER),
        ("text", "text", TableValueType.TEXT),
        ("ref", "ref", TableValueType.TEXT),
        ("confidence", "confidence", TableValueType.NUMBER),
        ("min_confidence", "min_confidence", TableValueType.NUMBER),
        ("page_confidence", "page_confidence", TableValueType.NUMBER),
    ]
    assert output.blocks.rows == [
        {
            "page": 0,
            "index": index,
            "kind": kind,
            "x0": 1,
            "y0": 2,
            "x1": 30,
            "y1": 40,
            "text": text,
            "ref": ref,
            "confidence": 0.8 if index == 0 and granularity == "block" else None,
            "min_confidence": 0.5 if index == 0 and granularity == "block" else None,
            "page_confidence": 0.9 if granularity == "page" else None,
        }
        for index, (kind, text, ref) in enumerate(
            [
                ("text", " A \n title ", None),
                ("table", "<table>10</table>", "tbl-0.html"),
                ("image", "img-0.jpeg", "img-0.jpeg"),
            ]
        )
    ]


def test_regions_labels_normalization_and_empty_block_pages() -> None:
    output = build_ocr_output(
        response(
            [
                page(
                    blocks=[
                        block("title"),
                        block("image", image_id="img-0.jpeg"),
                        block("table", table_id="tbl-0.html"),
                        block("table", content=" fallback  table "),
                        block(content="x" * 121),
                        block(content=" \n "),
                        block(
                            top_left_x=20,
                            top_left_y=30,
                            bottom_right_x=-5,
                            bottom_right_y=-10,
                        ),
                    ]
                )
            ]
        ),
        MistralOcrConfig(),
    )
    regions = output.regions
    assert [(p.width, p.height, p.index) for p in regions.pages] == [(600, 800, 0)]
    assert [(r.kind, r.label) for r in regions.regions] == [
        ("title", "A title"),
        ("image", "img-0.jpeg"),
        ("table", "tbl-0.html"),
        ("table", "fallback table"),
        ("text", "x" * 120 + "…"),
        ("text", None),
        ("text", "A title"),
    ]
    assert regions.regions[-1] == ImageRegion(
        x0=0, y0=0, x1=20, y1=30, kind="text", label="A title"
    )
    row = output.blocks.rows[-1]
    assert (row["x0"], row["y0"], row["x1"], row["y1"]) == (
        regions.regions[-1].x0,
        regions.regions[-1].y0,
        regions.regions[-1].x1,
        regions.regions[-1].y1,
    )


@pytest.mark.parametrize("blocks", [None, []])
def test_images_fallback_only_when_blocks_absent(blocks: list[object] | None) -> None:
    images: list[dict[str, object]] = [
        {
            "id": "complete",
            "top_left_x": 20,
            "top_left_y": 30,
            "bottom_right_x": -5,
            "bottom_right_y": -10,
        }
    ]
    for missing in ("top_left_x", "top_left_y", "bottom_right_x", "bottom_right_y"):
        images.append({**images[0], missing: None})
    output = build_ocr_output(
        response([page(blocks=blocks, images=images)]), MistralOcrConfig()
    )
    assert output.blocks.rows == []
    assert output.regions.regions == (
        [ImageRegion(x0=0, y0=0, x1=20, y1=30, kind="image", label="complete")]
        if blocks is None
        else []
    )


@pytest.mark.parametrize(
    "dimensions",
    [
        None,
        {"dpi": 300, "width": 0, "height": 800},
        {"dpi": 300, "width": 600, "height": 0},
    ],
)
def test_page_without_dimensions_fails_with_page_context(dimensions: object) -> None:
    with pytest.raises(
        MistralOcrProviderError, match="OCR page 0 reports no pixel dimensions"
    ):
        _ = build_ocr_output(
            response([page(markdown="text", dimensions=dimensions, blocks=[block()])]),
            MistralOcrConfig(),
        )


def test_region_pages_and_boxes_preserve_provider_order() -> None:
    output = build_ocr_output(
        response(
            [
                page(index=3, blocks=[block()]),
                page(index=1, blocks=[block("image", image_id="figure")]),
            ]
        ),
        MistralOcrConfig(),
    )
    assert [p.index for p in output.regions.pages] == [3, 1]
    assert [r.page for r in output.regions.regions] == [3, 1]

import base64

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
    assert [regions.page_index for regions in output.regions] == [0, 3]


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
    regions = output.regions[0]
    assert (regions.width, regions.height, regions.page_index) == (600, 800, 0)
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
    assert output.regions[0].regions == (
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
def test_page_without_dimensions_keeps_other_outputs(
    dimensions: object, caplog: pytest.LogCaptureFixture
) -> None:
    output = build_ocr_output(
        response([page(markdown="text", dimensions=dimensions, blocks=[block()])]),
        MistralOcrConfig(),
    )
    assert output.markdown.markdown == "text"
    assert len(output.blocks.rows) == 1
    assert output.regions == []
    assert "Skipping regions for OCR page 0" in caplog.text


@pytest.mark.parametrize(
    "media_type, content, expected",
    [
        ("image/jpeg", b"\xff\xd8jpeg", "image/jpeg"),
        (None, b"\x89PNGpng", "image/png"),
        ("image/unknown", b"RIFFabcdWEBPpayload", "image/webp"),
        ("image/tiff", b"tiff", "image/tiff"),
        ("image/bmp", b"bmp", "image/bmp"),
    ],
)
def test_figures_decode_data_urls_or_sniff_bare_bytes(
    media_type: str | None, content: bytes, expected: str
) -> None:
    encoded = base64.b64encode(content).decode("ascii")
    if media_type is not None:
        encoded = f"data:{media_type};base64,{encoded}"
    output = build_ocr_output(
        response([page(images=[{"id": "img-0.jpeg", "image_base64": encoded}])]),
        MistralOcrConfig(),
    )
    assert len(output.figures) == 1
    assert output.figures[0].content == content
    assert output.figures[0].content_type == expected
    assert output.figures[0].filename == "img-0.jpeg"


def test_figures_skip_unknown_and_empty_and_preserve_page_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    output = build_ocr_output(
        response(
            [
                page(
                    images=[
                        {"id": "unknown", "image_base64": "aGVsbG8="},
                        {"id": "empty", "image_base64": ""},
                        {"id": "first", "image_base64": "/9g="},
                    ]
                ),
                page(index=2, images=[{"id": "second", "image_base64": "iVBORw=="}]),
            ]
        ),
        MistralOcrConfig(),
    )
    assert [figure.filename for figure in output.figures] == ["first", "second"]
    assert "Skipping OCR figure 'unknown'" in caplog.text


@pytest.mark.parametrize(
    "encoded", ["not base64!", "data:image/jpeg;base64,!", "data:image/jpeg,abcd"]
)
def test_invalid_figure_base64_raises(encoded: str) -> None:
    with pytest.raises(MistralOcrProviderError, match="figure 'broken'.*base64"):
        _ = build_ocr_output(
            response([page(images=[{"id": "broken", "image_base64": encoded}])]),
            MistralOcrConfig(),
        )

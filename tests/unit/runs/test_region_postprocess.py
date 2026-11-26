import warnings
from collections.abc import Sequence
from math import cos, radians, sin
from uuid import UUID, uuid4

from grafy_core.config_ui import validate_config_ui_schema
from grafy_core.contracts.ocr import PixelPoint, TextRegion, TiffPage
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext
from grafy_core.node_ports import Ref
from grafy_plugin_map_toponyms.region_postprocess import (
    PostprocessOptions,
    PostprocessRegionsConfig,
    PostprocessRegionsInput,
    PostprocessTiffRegionsNode,
    postprocess_regions,
)
from grafy_plugin_map_toponyms.region_postprocess.geometry import (
    axis_vector,
    measure_region,
    project_interval,
)
from grafy_plugin_map_toponyms.text_regions import TiffPixelWindow, TiffTextRegions
from shapely import Polygon

type Box = list[PixelPoint]


def _rectangle(left: float, top: float, right: float, bottom: float) -> Box:
    return [(left, top), (right, top), (right, bottom), (left, bottom)]


def _bar(
    center_x: float, center_y: float, length: float, thickness: float, angle: float
) -> Box:
    tilt = radians(angle)
    axis_x, axis_y = cos(tilt), sin(tilt)
    normal_x, normal_y = -axis_y, axis_x
    half_length, half_thickness = length / 2, thickness / 2
    return [
        (
            center_x + half_length * axis_x + half_thickness * normal_x,
            center_y + half_length * axis_y + half_thickness * normal_y,
        ),
        (
            center_x + half_length * axis_x - half_thickness * normal_x,
            center_y + half_length * axis_y - half_thickness * normal_y,
        ),
        (
            center_x - half_length * axis_x - half_thickness * normal_x,
            center_y - half_length * axis_y - half_thickness * normal_y,
        ),
        (
            center_x - half_length * axis_x + half_thickness * normal_x,
            center_y - half_length * axis_y + half_thickness * normal_y,
        ),
    ]


def _region(
    polygon: Box, text: str | None = None, score: float | None = None
) -> TextRegion:
    return TextRegion(polygon=polygon, text=text, score=score)


def _bounds(polygon: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _texts(regions: Sequence[TextRegion]) -> list[str | None]:
    return [region.text for region in regions]


def _near(actual: float, expected: float, tol: float = 0.05) -> None:
    assert abs(actual - expected) <= tol, (actual, expected)


def _projected_span(
    points: Sequence[tuple[float, float]], axis: tuple[float, float]
) -> float:
    low, high = project_interval(points, axis)
    return high - low


def _shift(origin: tuple[float, float], distance: float, angle: float) -> tuple[float, float]:
    tilt = radians(angle)
    return origin[0] + distance * cos(tilt), origin[1] + distance * sin(tilt)


def test_postprocess_keeps_empty_input_empty() -> None:
    result = postprocess_regions([])

    assert result.regions == []
    assert result.dropped == []
    assert result.stats.input_regions == 0
    assert result.stats.output_regions == 0
    assert result.stats.invalid_dropped == 0
    assert result.stats.estimated_letter_height == 0.0


def test_postprocess_preserves_a_single_box() -> None:
    region = _region(_rectangle(10, 10, 50, 30), "only", 0.5)

    result = postprocess_regions([region])

    assert len(result.regions) == 1
    assert result.dropped == []
    kept = result.regions[0]
    assert kept.text == "only"
    assert kept.score == 0.5
    assert len(kept.polygon) == 4
    assert _bounds(kept.polygon) == (10.0, 10.0, 50.0, 30.0)
    assert result.stats.output_regions == 1
    assert result.stats.estimated_letter_height == 20.0


def test_postprocess_repairs_a_bowtie_and_counts_a_degenerate_polygon() -> None:
    bowtie = _region(
        [(10.0, 10.0), (50.0, 50.0), (10.0, 50.0), (50.0, 10.0)], "bow", 0.4
    )
    flat = _region([(5.0, 5.0), (15.0, 15.0), (25.0, 25.0)], "flat", 0.2)
    assert Polygon(bowtie.polygon).is_valid is False

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        result = postprocess_regions([bowtie, flat])

    assert _texts(result.regions) == ["bow"]
    assert result.dropped == []
    repaired = Polygon(result.regions[0].polygon)
    assert repaired.is_valid
    assert repaired.area == 400.0
    assert _bounds(result.regions[0].polygon) == (10.0, 30.0, 50.0, 50.0)
    assert result.regions[0].score == 0.4
    assert result.stats.invalid_dropped == 1
    assert result.stats.input_regions == 2
    assert result.stats.output_regions == 1


def test_postprocess_drops_low_scores_and_keeps_missing_scores() -> None:
    result = postprocess_regions(
        [
            _region(_rectangle(10, 10, 90, 30), "low", 0.2),
            _region(_rectangle(10, 80, 90, 100), "high", 0.9),
            _region(_rectangle(10, 160, 90, 180), "none", None),
            _region(_rectangle(10, 240, 90, 260), "edge", 0.5),
        ],
        PostprocessOptions(min_score=0.5),
    )

    assert _texts(result.regions) == ["high", "none", "edge"]
    assert [region.score for region in result.regions] == [0.9, None, 0.5]
    assert _texts(result.dropped) == ["low"]
    assert result.stats.score_dropped == 1
    assert result.stats.output_regions == 3


def test_postprocess_drops_micro_specks_before_letter_height() -> None:
    # Eight 3px specks would pull the letter-height estimate down to the dust
    # and then the real letter would look like a watermark. They have to go first.
    specks = [
        _region(_rectangle(index * 6, 0, index * 6 + 3, 3), f"s{index}", 0.9)
        for index in range(8)
    ]
    letter = _region(_rectangle(200, 100, 280, 120), "letter", 0.9)

    result = postprocess_regions([*specks, letter])

    assert _texts(result.regions) == ["letter"]
    assert _texts(result.dropped) == [f"s{index}" for index in range(8)]
    assert result.stats.micro_specks_dropped == 8
    assert result.stats.outliers_dropped == 0
    assert result.stats.estimated_letter_height == 20.0


def test_postprocess_drops_giant_watermarks_before_containment() -> None:
    words = [
        _region(_rectangle(40 + index * 160, 40, 130 + index * 160, 60), f"word{index}", 0.8)
        for index in range(6)
    ]
    parcel_79 = _region(_rectangle(286, 289, 314, 311), "79", 0.7)
    parcel_76 = _region(_rectangle(686, 289, 714, 311), "76", 0.7)
    gray = _region(_rectangle(210, 257, 390, 342), "Серый", 0.6)
    digger = _region(_rectangle(610, 257, 790, 342), "Копатель", 0.6)
    assert Polygon(gray.polygon).covers(Polygon(parcel_79.polygon))
    assert Polygon(digger.polygon).covers(Polygon(parcel_76.polygon))
    assert _bounds(gray.polygon)[3] - _bounds(gray.polygon)[1] == 85.0

    result = postprocess_regions([*words, gray, parcel_79, digger, parcel_76])

    assert _texts(result.regions) == [
        "word0",
        "word1",
        "word2",
        "word3",
        "word4",
        "word5",
        "79",
        "76",
    ]
    assert _texts(result.dropped) == ["Серый", "Копатель"]
    assert result.stats.outliers_dropped == 2
    assert result.stats.overlaps_resolved == 0
    assert result.stats.estimated_letter_height == 20.0


def test_postprocess_applies_hard_height_and_area_caps() -> None:
    tall = _region(_rectangle(10, 10, 110, 50), "tall", 0.9)
    small = _region(_rectangle(200, 10, 260, 30), "ok", 0.9)

    by_height = postprocess_regions(
        [tall, small], PostprocessOptions(max_height_px=30)
    )
    by_area = postprocess_regions(
        [tall, small], PostprocessOptions(max_area_px=2000)
    )

    assert _texts(by_height.regions) == ["ok"]
    assert _texts(by_height.dropped) == ["tall"]
    assert by_height.stats.outliers_dropped == 1
    assert _texts(by_area.regions) == ["ok"]
    assert _texts(by_area.dropped) == ["tall"]
    assert by_area.stats.outliers_dropped == 1


def test_postprocess_merges_shifted_duplicates_at_the_max_score() -> None:
    result = postprocess_regions(
        [
            _region(_rectangle(100, 100, 220, 122), "пещанка", 0.6),
            _region(_rectangle(154, 100, 274, 122), "пещанка", 0.9),
            _region(_rectangle(400, 300, 520, 322), "шутовна", 0.4),
            _region(_rectangle(454, 300, 574, 322), "шутовна", 0.88),
        ]
    )

    assert [(region.text, region.score) for region in result.regions] == [
        ("пещанка", 0.9),
        ("шутовна", 0.88),
    ]
    assert result.dropped == []
    assert _bounds(result.regions[0].polygon) == (100.0, 100.0, 274.0, 122.0)
    assert _bounds(result.regions[1].polygon) == (400.0, 300.0, 574.0, 322.0)
    assert result.stats.overlaps_resolved == 2
    assert result.stats.spans_joined == 0


def test_postprocess_merges_a_detached_trailing_fragment() -> None:
    fragment = _region(_rectangle(188, 101, 204, 119), "о", 0.7)
    measured = measure_region(fragment)
    assert measured is not None
    assert measured.angle == 90.0
    assert measured.aspect < 1.5

    result = postprocess_regions(
        [
            _region(_rectangle(100, 100, 200, 120), "голубо", 0.8),
            fragment,
            _region(_rectangle(400, 200, 520, 220), "щеглиц", 0.8),
            _region(_rectangle(490, 200, 530, 220), "ба", 0.6),
        ]
    )

    assert _texts(result.regions) == ["голубо о", "щеглиц ба"]
    assert [region.score for region in result.regions] == [0.8, 0.8]
    assert _bounds(result.regions[0].polygon) == (100.0, 100.0, 204.0, 120.0)
    assert _bounds(result.regions[1].polygon) == (400.0, 200.0, 530.0, 220.0)
    assert result.dropped == []
    assert result.stats.overlaps_resolved == 2
    assert result.stats.spans_joined == 0


def test_postprocess_suppresses_a_nested_sub_box_in_smart_mode() -> None:
    outer = _region(_rectangle(100, 300, 220, 322), "проивши", 0.7)
    inner = _region(_rectangle(120, 302, 170, 320), "про", 0.95)

    result = postprocess_regions([outer, inner])

    assert len(result.regions) == 1
    assert result.regions[0].text == "проивши"
    assert result.regions[0].score == 0.7
    assert _bounds(result.regions[0].polygon) == _bounds(outer.polygon)
    assert _texts(result.dropped) == ["про"]
    assert result.dropped[0].score == 0.95
    assert result.stats.overlaps_resolved == 1


def test_postprocess_keep_best_does_not_expand_the_winner() -> None:
    weaker = _region(_rectangle(100, 100, 220, 122), "пещанка", 0.4)
    stronger = _region(_rectangle(130, 100, 250, 122), "пещанка", 0.9)

    kept = postprocess_regions(
        [weaker, stronger], PostprocessOptions(overlap_mode="keep_best")
    )
    merged = postprocess_regions(
        [weaker, stronger], PostprocessOptions(overlap_mode="merge")
    )

    assert len(kept.regions) == 1
    assert kept.regions[0].score == 0.9
    assert _bounds(kept.regions[0].polygon) == _bounds(stronger.polygon)
    assert _texts(kept.dropped) == ["пещанка"]
    assert kept.dropped[0].score == 0.4
    assert _bounds(kept.dropped[0].polygon) == _bounds(weaker.polygon)
    assert len(merged.regions) == 1
    assert merged.regions[0].score == 0.9
    assert merged.dropped == []
    assert _bounds(merged.regions[0].polygon) == (100.0, 100.0, 250.0, 122.0)


def test_postprocess_leaves_cross_angled_labels_apart() -> None:
    result = postprocess_regions(
        [
            _region(_bar(200, 200, 90, 16, 0), "horiz", 0.8),
            _region(_bar(200, 200, 90, 16, 80), "diag", 0.8),
        ]
    )

    assert _texts(result.regions) == ["diag", "horiz"]
    assert result.dropped == []
    assert result.stats.overlaps_resolved == 0
    assert result.stats.spans_joined == 0


def test_postprocess_does_not_fuse_stacked_lines_at_descenders() -> None:
    upper = _region(_rectangle(100, 100, 260, 120), "upper", 0.8)
    lower = _region(_rectangle(100, 111, 260, 131), "lower", 0.8)

    result = postprocess_regions([upper, lower])

    assert _texts(result.regions) == ["upper", "lower"]
    assert _bounds(result.regions[0].polygon) == _bounds(upper.polygon)
    assert _bounds(result.regions[1].polygon) == _bounds(lower.polygon)
    assert result.stats.overlaps_resolved == 0
    assert result.stats.spans_joined == 0


def test_postprocess_merges_a_diagonal_overlap_chain() -> None:
    angle = -50.0
    start = (300.0, 300.0)
    centers = [start, _shift(start, 14, angle), _shift(start, 28, angle)]
    lengths = (36.0, 28.0, 40.0)
    fragments = [
        _region(_bar(*center, length, 16, angle), text, score)
        for center, length, text, score in zip(
            centers, lengths, ("ёв", "о", "ая"), (0.7, 0.6, 0.8), strict=True
        )
    ]

    result = postprocess_regions(fragments)

    assert _texts(result.regions) == ["ёв о ая"]
    assert result.regions[0].score == 0.8
    assert result.dropped == []
    assert result.stats.overlaps_resolved == 2
    assert result.stats.spans_joined == 0


def test_postprocess_joins_square_prefixes_on_the_word_axis() -> None:
    prefix = _region(_rectangle(100, 100, 116, 118), "д:", 0.8)
    measured = measure_region(prefix)
    assert measured is not None
    assert measured.width == 18.0
    assert measured.height == 16.0
    assert measured.angle == 90.0
    assert measured.aspect < 1.5

    result = postprocess_regions(
        [
            prefix,
            _region(_rectangle(122, 100, 230, 120), "проивши", 0.8),
            _region(_rectangle(236, 101, 310, 119), "ничи", 0.8),
            _region(_rectangle(100, 180, 116, 198), "сел:", 0.8),
            _region(_rectangle(122, 180, 230, 200), "щеглица", 0.8),
            _region(_rectangle(100, 260, 116, 278), "Ре:", 0.8),
            _region(_rectangle(122, 260, 240, 280), "щеглянка", 0.8),
            _region(_rectangle(100, 340, 116, 358), "сл:", 0.8),
            _region(_rectangle(122, 340, 230, 360), "Заборья", 0.8),
        ]
    )

    assert _texts(result.regions) == [
        "д: проивши ничи",
        "сел: щеглица",
        "Ре: щеглянка",
        "сл: Заборья",
    ]
    assert _bounds(result.regions[0].polygon) == (100.0, 100.0, 310.0, 120.0)
    assert result.stats.overlaps_resolved == 0
    assert result.stats.spans_joined == 5


def test_postprocess_joins_diagonal_word_fragments() -> None:
    angle = -45.0
    start = (300.0, 300.0)
    first = _region(_bar(*start, 40, 16, angle), "ещ", 0.8)
    second = _region(_bar(*_shift(start, 48, angle), 50, 16, angle), "анной", 0.8)

    result = postprocess_regions([first, second])

    assert _texts(result.regions) == ["ещ анной"]
    assert result.regions[0].score == 0.8
    assert result.dropped == []
    assert result.stats.overlaps_resolved == 0
    assert result.stats.spans_joined == 1
    span = measure_region(result.regions[0])
    assert span is not None
    _near(span.angle, -45.0)
    assert span.width > 50.0
    _near(span.height, 16.0, tol=1.0)


def test_postprocess_joins_near_vertical_fragments_across_the_angle_wrap() -> None:
    upper = _region(_bar(400, 80, 40, 14, -85), "верх", 0.8)
    lower = _region(_bar(400, 140, 40, 14, 85), "низ", 0.8)
    upper_box = measure_region(upper)
    lower_box = measure_region(lower)
    assert upper_box is not None and lower_box is not None
    _near(upper_box.angle, -85.0)
    _near(lower_box.angle, 85.0)

    result = postprocess_regions([upper, lower])

    assert _texts(result.regions) == ["верх низ"]
    assert result.stats.spans_joined == 1
    assert result.stats.overlaps_resolved == 0
    left, top, right, bottom = _bounds(result.regions[0].polygon)
    assert bottom - top > (right - left) * 3


def test_postprocess_keeps_stacked_parallel_lines_apart() -> None:
    result = postprocess_regions(
        [
            _region(_rectangle(100, 100, 116, 118), "се", 0.8),
            _region(_rectangle(122, 100, 230, 120), ":щеглиц", 0.8),
            _region(_rectangle(236, 102, 270, 118), "ба", 0.7),
            _region(_rectangle(100, 160, 116, 178), "Ре:", 0.8),
            _region(_rectangle(122, 160, 240, 180), "щеглянка", 0.8),
            _region(_rectangle(100, 220, 116, 238), "сел:", 0.8),
            _region(_rectangle(122, 220, 230, 240), "щеглица", 0.8),
        ]
    )

    assert _texts(result.regions) == [
        "се :щеглиц ба",
        "Ре: щеглянка",
        "сел: щеглица",
    ]
    assert _bounds(result.regions[0].polygon) == (100.0, 100.0, 270.0, 120.0)
    assert _bounds(result.regions[1].polygon) == (100.0, 160.0, 240.0, 180.0)
    assert _bounds(result.regions[2].polygon) == (100.0, 220.0, 230.0, 240.0)
    assert result.stats.spans_joined == 4


def test_postprocess_respects_the_chain_member_cap() -> None:
    boxes = [
        _region(_rectangle(100 + index * 50, 100, 140 + index * 50, 118), f"p{index}", 0.8)
        for index in range(5)
    ]

    capped = postprocess_regions(boxes, PostprocessOptions(max_chain_members=2))
    uncapped = postprocess_regions(boxes)

    assert _texts(capped.regions) == ["p0 p1", "p2 p3", "p4"]
    assert capped.stats.spans_joined == 2
    assert _texts(uncapped.regions) == ["p0 p1 p2 p3 p4"]
    assert uncapped.stats.spans_joined == 4


def test_postprocess_joins_text_left_to_right_and_skips_duplicate_text() -> None:
    result = postprocess_regions(
        [
            _region(_rectangle(220, 100, 280, 118), "анка", 0.5),
            _region(_rectangle(100, 100, 150, 118), "пещ", 0.9),
            _region(_rectangle(160, 100, 210, 118), "анка", 0.6),
        ]
    )

    assert len(result.regions) == 1
    assert result.regions[0].text == "пещ анка"
    assert result.regions[0].score == 0.9
    assert _bounds(result.regions[0].polygon) == (100.0, 100.0, 280.0, 118.0)
    assert result.stats.spans_joined == 2


def test_postprocess_drops_an_isolated_symbol_after_prefixes_join() -> None:
    result = postprocess_regions(
        [
            _region(_rectangle(100, 100, 116, 118), "д:", 0.8),
            _region(_rectangle(122, 100, 240, 120), "проивши", 0.8),
            _region(_rectangle(400, 400, 408, 408), "tree", 0.5),
        ]
    )

    assert _texts(result.regions) == ["д: проивши"]
    assert _bounds(result.regions[0].polygon) == (100.0, 100.0, 240.0, 120.0)
    assert _texts(result.dropped) == ["tree"]
    assert result.stats.spans_joined == 1
    assert result.stats.noise_dropped == 1
    assert result.stats.micro_specks_dropped == 0


def test_postprocess_filters_a_thin_tree_row_only_when_asked() -> None:
    rows = [
        _region(_rectangle(100, 100, 136, 108), "trees", 0.5),
        _region(_rectangle(100, 200, 200, 220), "word", 0.8),
        _region(_rectangle(300, 200, 400, 220), "word2", 0.8),
        _region(_rectangle(500, 200, 600, 220), "word3", 0.8),
        _region(_rectangle(700, 200, 800, 220), "word4", 0.8),
    ]
    tree = measure_region(rows[0])
    assert tree is not None
    assert tree.height == 8.0
    assert tree.width == 36.0
    assert tree.aspect == 4.5

    kept = postprocess_regions(rows, PostprocessOptions(drop_elongated_small=False))
    dropped = postprocess_regions(rows, PostprocessOptions(drop_elongated_small=True))

    assert "trees" in _texts(kept.regions)
    assert kept.stats.noise_dropped == 0
    assert _texts(dropped.regions) == ["word", "word2", "word3", "word4"]
    assert _texts(dropped.dropped) == ["trees"]
    assert dropped.stats.noise_dropped == 1


def test_postprocess_applies_absolute_size_floors() -> None:
    narrow = _region(_rectangle(100, 100, 130, 120), "small", 0.8)
    wide = _region(_rectangle(400, 100, 480, 120), "large", 0.8)
    short = _region(_rectangle(100, 100, 180, 118), "short", 0.8)
    tall = _region(_rectangle(400, 100, 480, 128), "tallok", 0.8)
    tiny = _region(_rectangle(100, 100, 140, 120), "tinyarea", 0.8)
    roomy = _region(_rectangle(400, 100, 480, 120), "bigarea", 0.8)

    by_width = postprocess_regions(
        [narrow, wide], PostprocessOptions(min_width_px=40)
    )
    by_height = postprocess_regions(
        [short, tall], PostprocessOptions(min_height_px=22)
    )
    by_area = postprocess_regions(
        [tiny, roomy], PostprocessOptions(min_area_px=1000)
    )

    assert _texts(by_width.regions) == ["large"]
    assert _texts(by_width.dropped) == ["small"]
    assert _texts(by_height.regions) == ["tallok"]
    assert _texts(by_height.dropped) == ["short"]
    assert _texts(by_area.regions) == ["bigarea"]
    assert _texts(by_area.dropped) == ["tinyarea"]
    assert by_width.stats.noise_dropped == 1
    assert by_height.stats.noise_dropped == 1
    assert by_area.stats.noise_dropped == 1


def test_postprocess_shapes_the_output_polygon() -> None:
    elbow = [
        (100.0, 100.0),
        (160.0, 100.0),
        (160.0, 115.0),
        (115.0, 115.0),
        (115.0, 150.0),
        (100.0, 150.0),
    ]
    jag = [
        (100.0, 100.0),
        (130.0, 100.0),
        (131.0, 100.8),
        (160.0, 100.0),
        (160.0, 122.0),
        (100.0, 122.0),
    ]

    oriented = postprocess_regions(
        [_region(elbow, "L")], PostprocessOptions(polygon_shape="oriented_rect")
    )
    hull = postprocess_regions(
        [_region(elbow, "L")], PostprocessOptions(polygon_shape="convex_hull")
    )
    original = postprocess_regions(
        [_region(elbow, "L")], PostprocessOptions(polygon_shape="keep_original")
    )
    simplified = postprocess_regions(
        [_region(jag, "jag")],
        PostprocessOptions(polygon_shape="simplified", simplify_tolerance_px=1.5),
    )
    kept_jag = postprocess_regions(
        [_region(jag, "jag")], PostprocessOptions(polygon_shape="keep_original")
    )

    assert len(oriented.regions[0].polygon) == 4
    assert _bounds(oriented.regions[0].polygon) == (100.0, 100.0, 160.0, 150.0)
    assert len(hull.regions[0].polygon) == 5
    assert (115.0, 115.0) not in hull.regions[0].polygon
    assert list(original.regions[0].polygon) == elbow
    assert list(kept_jag.regions[0].polygon) == jag
    assert len(simplified.regions[0].polygon) == 4
    assert (131.0, 100.8) not in simplified.regions[0].polygon


def test_postprocess_pads_more_along_the_reading_axis() -> None:
    raw = _bar(200, 200, 80, 16, 30)
    result = postprocess_regions(
        [_region(raw, "pad", 0.8)],
        PostprocessOptions(pad_along_px=6, pad_across_px=2),
    )
    axis = axis_vector(30)
    normal = (-axis[1], axis[0])
    padded = result.regions[0].polygon
    along = _projected_span(padded, axis) - _projected_span(raw, axis)
    across = _projected_span(padded, normal) - _projected_span(raw, normal)

    assert len(result.regions) == 1
    assert along > across
    _near(along, 12.0)
    _near(across, 4.0)


def test_postprocess_clamps_coordinates_to_the_page() -> None:
    result = postprocess_regions(
        [
            _region(_rectangle(0, 0, 30, 16), "origin", 0.8),
            _region(_rectangle(180, 140, 210, 160), "corner", 0.8),
            _region(_rectangle(80, 60, 120, 80), "mid", 0.8),
        ],
        PostprocessOptions(pad_along_px=6, pad_across_px=2),
        max_x=200,
        max_y=150,
    )

    assert _texts(result.regions) == ["origin", "mid", "corner"]
    for region in result.regions:
        for x, y in region.polygon:
            assert 0.0 <= x <= 200.0
            assert 0.0 <= y <= 150.0
    assert _bounds(result.regions[0].polygon) == (0.0, 0.0, 36.0, 18.0)
    assert _bounds(result.regions[1].polygon) == (74.0, 58.0, 126.0, 82.0)
    assert _bounds(result.regions[2].polygon) == (174.0, 138.0, 200.0, 150.0)


def _detected(regions: list[TextRegion], *, page: int = 0) -> TiffTextRegions:
    return TiffTextRegions(
        source=Ref[TiffFile](
            artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
        ),
        window=TiffPixelWindow(page=page, col=0, row=0, width=800, height=600),
        regions=regions,
    )


async def test_node_runs_without_a_page_opener() -> None:
    detected = _detected(
        [
            _region(_rectangle(100, 100, 180, 120), "kept", 0.8),
            _region(_rectangle(100, 200, 180, 220), "low", 0.2),
        ]
    )
    context = NodeExecutionContext(workspace_id=uuid4())

    output = await PostprocessTiffRegionsNode().run(
        context,
        PostprocessRegionsConfig(preset="custom", min_score=0.5),
        PostprocessRegionsInput(regions=detected),
    )

    assert output.regions.source == detected.source
    assert output.regions.window == detected.window
    assert output.dropped.source == detected.source
    assert output.dropped.window == detected.window
    assert _texts(output.regions.regions) == ["kept"]
    assert _texts(output.dropped.regions) == ["low"]
    assert context.output_metadata == {
        "input_regions": 2,
        "invalid_dropped": 0,
        "score_dropped": 1,
        "outliers_dropped": 0,
        "micro_specks_dropped": 0,
        "overlaps_resolved": 0,
        "spans_joined": 0,
        "noise_dropped": 0,
        "output_regions": 1,
        "estimated_letter_height": 20.0,
    }


async def test_node_clamps_padding_to_the_opened_page() -> None:
    detected = _detected(
        [_region(_rectangle(460, 370, 520, 410), "edge", 0.8)],
        page=2,
    )
    context = NodeExecutionContext(workspace_id=uuid4())

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        assert col >= 0 and row >= 0 and width > 0 and height > 0
        return b""

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        assert workspace_id == context.workspace_id
        assert artifact_id == detected.source.artifact_id
        assert page == 2
        return TiffPage(500, 400, read, source_sha256="ab" * 32, page=page)

    output = await PostprocessTiffRegionsNode(open_page).run(
        context,
        PostprocessRegionsConfig(pad_along_px=6, pad_across_px=2),
        PostprocessRegionsInput(regions=detected),
    )

    assert len(output.regions.regions) == 1
    assert output.dropped.regions == []
    polygon = output.regions.regions[0].polygon
    assert max(x for x, _ in polygon) == 500.0
    assert max(y for _, y in polygon) == 400.0
    for x, y in polygon:
        assert 0.0 <= x <= 500.0
        assert 0.0 <= y <= 400.0
    assert context.output_metadata["output_regions"] == 1
    assert context.output_metadata["input_regions"] == 1


def test_postprocess_config_ui_schema_is_valid() -> None:
    assert (
        validate_config_ui_schema(
            PostprocessRegionsConfig.model_json_schema(),
            input_ports={"regions"},
        )
        == []
    )


def test_postprocess_presets_produce_distinct_tuned_options() -> None:
    balanced = PostprocessRegionsConfig(preset="balanced").to_options()
    conservative = PostprocessRegionsConfig(preset="conservative").to_options()
    aggressive = PostprocessRegionsConfig(
        preset="aggressive", polygon_shape="oriented_rect", pad_along_px=4.0
    ).to_options()

    assert balanced.overlap_mode == "smart"
    assert balanced.polygon_shape == "keep_original"
    assert not balanced.drop_elongated_small
    assert conservative.overlap_mode == "keep_best"
    assert conservative.max_gap_heights < balanced.max_gap_heights
    assert aggressive.drop_elongated_small
    assert aggressive.max_gap_heights > balanced.max_gap_heights
    assert aggressive.polygon_shape == "oriented_rect"
    assert aggressive.pad_along_px == 4.0


def test_postprocess_does_not_join_tall_two_line_box_with_off_center_neighbor() -> None:
    two_line_box = _region(_rectangle(100, 100, 260, 200), "С: старое село 14", 0.9)
    side_settlement = _region(_rectangle(270, 155, 380, 213), "д: суков", 0.9)

    result = postprocess_regions([two_line_box, side_settlement])

    assert len(result.regions) == 2
    assert result.stats.spans_joined == 0

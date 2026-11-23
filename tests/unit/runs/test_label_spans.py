from math import cos, radians, sin
from uuid import uuid4

from grafy_core.artifacts import NoConfig
from grafy_core.contracts.ocr import PixelPoint, TextReading, TextRegion
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext
from grafy_core.node_ports import Ref
from grafy_core.table_contracts import TableValueType
from grafy_plugin_map_toponyms.label_nodes import (
    CollectMapPlacesInput,
    CollectMapPlacesNode,
    FilterReadingsConfig,
    FilterReadingsInput,
    FilterReadingsNode,
    PlacesTableInput,
    PlacesTableNode,
    PrepareLabelsConfig,
    PrepareLabelsInput,
    PrepareMapLabelsNode,
)
from grafy_plugin_map_toponyms.label_spans import (
    filter_readings,
    places_table,
    prepare_labels,
)
from grafy_plugin_map_toponyms.text_regions import TiffPixelWindow, TiffTextRegions
from grafy_plugin_map_toponyms.tiff_label_crop import (
    NATIVE_CROP_PIXEL_LIMIT,
    crop_pixels,
)
from grafy_plugin_map_toponyms.tiff_recognition import (
    TiffRecognizedRegion,
    TiffRecognizedText,
)
from shapely import Point, Polygon

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


def _region(polygon: Box, score: float | None = None) -> TextRegion:
    return TextRegion(polygon=polygon, score=score)


def _bounds(polygon: Box) -> tuple[float, float, float, float]:
    xs = [round(point[0], 6) for point in polygon]
    ys = [round(point[1], 6) for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _polygons(regions: list[TextRegion]) -> set[tuple[PixelPoint, ...]]:
    return {tuple(region.polygon) for region in regions}


def _read(
    polygon: Box, text: str | None, confidence: float | None = None
) -> TiffRecognizedRegion:
    reading = (
        None
        if text is None
        else TextReading(text=text, confidence=confidence, model="test")
    )
    return TiffRecognizedRegion(polygon=polygon, reading=reading)


def _text(region: TiffRecognizedRegion) -> str:
    reading = region.reading
    assert reading is not None
    return reading.text


def test_prepare_keeps_an_empty_scan_empty() -> None:
    assert prepare_labels([]) == []


def test_prepare_keeps_a_lone_box_unchanged() -> None:
    region = _region(_rectangle(100, 100, 180, 120), score=0.7)

    assert prepare_labels([region]) == [region]


def test_prepare_joins_a_span_and_drops_a_tree_symbol() -> None:
    first = _region(_rectangle(100, 100, 180, 120))
    second = _region(_rectangle(190, 100, 270, 120))
    far = _region(_rectangle(400, 100, 480, 120))
    other_line = _region(_rectangle(100, 200, 180, 220))
    tree = _region(_rectangle(200, 300, 208, 308))

    joined = prepare_labels([first, second, far, other_line, tree])

    polygons = [region.polygon for region in joined]
    assert len(polygons) == 3
    span = polygons[0]
    assert len(span) == 4
    assert _bounds(span) == (100.0, 100.0, 270.0, 120.0)
    assert polygons[1] == far.polygon
    assert polygons[2] == other_line.polygon
    assert all(max(point[1] for point in polygon) < 250 for polygon in polygons)


def test_prepare_refuses_two_bars_that_meet_at_a_steep_angle() -> None:
    horizontal = _region(_bar(200, 110, 160, 20, 0))
    steep = _region(_bar(200, 110, 160, 20, 80))

    joined = prepare_labels([horizontal, steep])

    assert _polygons(joined) == {tuple(horizontal.polygon), tuple(steep.polygon)}


def test_prepare_joins_transitively_along_one_baseline() -> None:
    boxes = [_region(_rectangle(left, 100, left + 80, 120)) for left in (100, 190, 280)]

    joined = prepare_labels(boxes)

    assert len(joined) == 1
    span = joined[0].polygon
    assert len(span) == 4
    assert _bounds(span) == (100.0, 100.0, 360.0, 120.0)


def test_prepare_keeps_a_taller_letter_apart() -> None:
    small = _region(_rectangle(100, 100, 180, 120))
    tall = _region(_rectangle(190, 80, 270, 120))
    next_small = _region(_rectangle(280, 100, 360, 120))

    joined = prepare_labels([small, tall, next_small])

    assert _polygons(joined) == {
        tuple(small.polygon),
        tuple(tall.polygon),
        tuple(next_small.polygon),
    }


def test_prepared_span_stays_inside_source_bounds_at_page_edge() -> None:
    first = _region(_bar(60, 40, 48, 20, 2))
    at_right_edge = _region(_bar(119, 46, 48, 20, 0))

    joined = prepare_labels([first, at_right_edge])

    assert len(joined) == 1
    assert max(x for x, _ in joined[0].polygon) == 143.0
    span = Polygon(joined[0].polygon)
    assert span.covers(Polygon(first.polygon))
    assert span.covers(Polygon(at_right_edge.polygon))


def test_prepare_drops_a_polygon_without_area() -> None:
    flat = _region([(5, 5), (6, 6), (7, 7)])
    letter = _region(_rectangle(100, 100, 180, 120))

    assert prepare_labels([flat, letter]) == [letter]
    assert prepare_labels([flat]) == []


def test_prepare_lists_the_upper_label_first() -> None:
    lower = _region(_rectangle(100, 300, 180, 320))
    upper = _region(_rectangle(100, 100, 180, 120))

    joined = prepare_labels([lower, upper])

    assert [region.polygon for region in joined] == [upper.polygon, lower.polygon]


def test_a_joined_span_carries_the_strongest_member_score() -> None:
    weak = _region(_rectangle(100, 100, 180, 120), score=0.4)
    strong = _region(_rectangle(190, 100, 270, 120), score=0.75)

    joined = prepare_labels([weak, strong])

    assert len(joined) == 1
    assert joined[0].score == 0.75
    assert joined[0].text is None


def test_filter_keeps_names_and_drops_marks_and_numbers() -> None:
    regions = [
        _read(_rectangle(100, 100, 180, 120), "Бѣлыничи", 0.81),
        _read(_rectangle(200, 100, 240, 120), "12", 0.99),
        _read(_rectangle(300, 100, 340, 120), "a", 0.99),
        _read(_rectangle(400, 100, 440, 120), "..", 0.99),
        _read(_rectangle(500, 100, 580, 120), "Krakow", 0.1),
        _read(_rectangle(600, 100, 680, 120), None),
        _read(_rectangle(700, 100, 780, 120), "Kotuszów", 0.9),
        _read(_rectangle(800, 100, 860, 120), "Lwów"),
    ]

    kept = filter_readings(regions)

    assert [_text(region) for region in kept] == ["Бѣлыничи", "Kotuszów", "Lwów"]


def test_places_table_writes_one_row_per_reading() -> None:
    recognized = TiffRecognizedText(
        source=Ref[TiffFile](
            artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
        ),
        window=TiffPixelWindow(page=3, col=0, row=0, width=600, height=400),
        regions=[
            _read(_rectangle(100, 100, 180, 120), "  Бѣлыничи  ", 0.81),
            _read(_rectangle(200, 100, 240, 120), "   ", 0.9),
            _read(_rectangle(320, 100, 450, 120), "реч. Березина", 0.95),
            _read(_rectangle(300, 100, 340, 120), None),
        ],
    )

    table = places_table(recognized)

    assert len(table.rows) == 1
    row = table.rows[0]
    assert row["name"] == "Бѣлыничи"
    assert row["page"] == 3
    assert row["confidence"] == 0.81
    assert row["width"] == 80
    assert row["height"] == 20


async def test_the_three_nodes_pass_their_artifact_through() -> None:
    context = NodeExecutionContext(workspace_id=uuid4())
    source = Ref[TiffFile](
        artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=2, col=0, row=0, width=600, height=400)
    detected = TiffTextRegions(
        source=source,
        window=window,
        regions=[
            _region(_rectangle(100, 100, 180, 120), score=0.62),
            _region(_rectangle(190, 100, 270, 120), score=0.71),
            _region(_rectangle(200, 300, 208, 308), score=0.3),
        ],
    )

    prepared = await PrepareMapLabelsNode().run(
        context, PrepareLabelsConfig(), PrepareLabelsInput(regions=detected)
    )
    assert prepared.regions.source == source
    assert prepared.regions.window == window
    assert len(prepared.regions.regions) == 1

    span = prepared.regions.regions[0]
    recognized = TiffRecognizedText(
        source=source,
        window=window,
        regions=[
            TiffRecognizedRegion(
                polygon=span.polygon,
                score=span.score,
                reading=TextReading(text="Бѣлыничи", confidence=0.81, model="test"),
            ),
            TiffRecognizedRegion(
                polygon=_rectangle(300, 300, 320, 320),
                reading=TextReading(text="12", confidence=0.99, model="test"),
            ),
        ],
    )

    filtered = await FilterReadingsNode().run(
        context,
        FilterReadingsConfig(),
        FilterReadingsInput(text=recognized),
    )
    assert filtered.text.source == source
    assert filtered.text.window == window
    assert [_text(region) for region in filtered.text.regions] == ["Бѣлыничи"]

    places = await PlacesTableNode().run(
        context, NoConfig(), PlacesTableInput(text=filtered.text)
    )
    table = places.places

    assert [(column.id, column.value_type) for column in table.columns] == [
        ("name", TableValueType.TEXT),
        ("confidence", TableValueType.NUMBER),
        ("page", TableValueType.INTEGER),
        ("x", TableValueType.NUMBER),
        ("y", TableValueType.NUMBER),
        ("width", TableValueType.NUMBER),
        ("height", TableValueType.NUMBER),
    ]
    row = table.rows[0]
    assert row["name"] == "Бѣлыничи"
    assert row["page"] == window.page
    x, y = row["x"], row["y"]
    assert isinstance(x, float)
    assert isinstance(y, float)
    assert Polygon(span.polygon).contains(Point(x, y))


def _worst_crop(regions: list[TextRegion]) -> int:
    return max(crop_pixels(region.polygon) for region in regions)


def test_prepare_joins_a_diagonal_run_whose_crop_needs_several_reads() -> None:
    # A name set along a diagonal: every neighbour pair is a legitimate join, so the
    # transitive join chains the whole run into one span whose axis-aligned box is
    # 1,658,944 pixels — more than one TIFF read covers. That no longer bounds the
    # join, because `read_label_crop` assembles such a box from several reads: the
    # run is still read once, as the one name it is.
    run = [
        _region(_bar(900 + 106 * step, 900 + 106 * step, 120, 40, 45))
        for step in range(12)
    ]
    assert _worst_crop(run) == 14_884

    joined = prepare_labels(run)

    assert len(joined) == 1
    assert _worst_crop(joined) == 1_658_944


def test_prepare_still_joins_a_diagonal_run_that_fits_one_read() -> None:
    run = [
        _region(_bar(900 + 106 * step, 900 + 106 * step, 120, 40, 45))
        for step in range(4)
    ]

    joined = prepare_labels(run)

    assert len(joined) == 1
    assert _worst_crop(joined) < NATIVE_CROP_PIXEL_LIMIT


def test_prepare_joins_a_long_label_line_along_the_page_axes() -> None:
    # Thousands of pixels of name is croppable when it is square to the page, so the
    # cap is on the read, not on how many boxes one span collects.
    run = [
        _region(_rectangle(1000 + 90 * step, 4000, 1080 + 90 * step, 4040))
        for step in range(30)
    ]

    joined = prepare_labels(run)

    assert len(joined) == 1
    assert _bounds(joined[0].polygon) == (1000.0, 4000.0, 3690.0, 4040.0)
    assert crop_pixels(joined[0].polygon) == 2698 * 48


async def test_collect_map_places_distinguishes_equal_pixels_on_different_sheets() -> (
    None
):
    context = NodeExecutionContext(workspace_id=uuid4())
    sources = [
        Ref[TiffFile](artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1)
        for _ in range(2)
    ]
    window = TiffPixelWindow(page=0, width=600, height=400)
    readings = [
        TiffRecognizedText(
            source=source,
            window=window,
            regions=[_read(_rectangle(100, 100, 180, 120), name, 0.90)],
        )
        for source, name in zip(sources, ("Корма", "Чауссы"), strict=True)
    ]

    result = await CollectMapPlacesNode().run(
        context, NoConfig(), CollectMapPlacesInput(readings=readings)
    )

    assert [
        (row["name"], row["source_artifact_id"], row["page"], row["x"], row["y"])
        for row in result.places.rows
    ] == [
        ("Корма", str(sources[0].artifact_id), 0, 140.0, 110.0),
        ("Чауссы", str(sources[1].artifact_id), 0, 140.0, 110.0),
    ]

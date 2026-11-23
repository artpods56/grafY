"""Group detected label boxes into spans and keep the readings that name places."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from math import atan2, cos, degrees, floor, hypot, isfinite, radians, sin

from grafy_core.contracts.ocr import PixelPoint, TextRegion
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType
from shapely import Polygon, make_valid  # pyright: ignore[reportUnknownVariableType]

from grafy_workbench.ocr.tiff_recognition import (
    TiffRecognizedRegion,
    TiffRecognizedText,
)

# A bar this long for its height is lettering, not a tree glyph or a hatch stroke.
_ELONGATED_RATIO = 2.5
_ELONGATED_FOR_LETTER_HEIGHT = 4
_LETTER_HEIGHT_PERCENTILE = 75.0
_SQUARE_RATIO = 2.0
_MIN_HEIGHT_RATIO = 0.55
# A caption or an abbreviation is set smaller than the name beside it, but a
# symbol is smaller again, so neighbours may differ in height only this much.
_MIN_NEIGHBOUR_HEIGHT = 0.65
_MAX_NEIGHBOUR_HEIGHT = 1.55
_NAME_LETTER_SHARE = 0.6
_SETTLEMENT_PREFIX = re.compile(
    r"^(?:(?:сел|с|дер|д)[.:]\s*|(?:село|деревня)\s+)", re.IGNORECASE
)
_WATER_PREFIX = re.compile(
    r"^(?:(?:реч|р|руч|оз)[.:]\s*|(?:река|ручей|озеро)\s+)", re.IGNORECASE
)

_PLACES_COLUMNS: tuple[TableColumn, ...] = (
    TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
    TableColumn(id="confidence", title="Confidence", value_type=TableValueType.NUMBER),
    TableColumn(id="page", title="Page", value_type=TableValueType.INTEGER),
    TableColumn(id="x", title="X", value_type=TableValueType.NUMBER),
    TableColumn(id="y", title="Y", value_type=TableValueType.NUMBER),
    TableColumn(id="width", title="Width", value_type=TableValueType.NUMBER),
    TableColumn(id="height", title="Height", value_type=TableValueType.NUMBER),
)


@dataclass(frozen=True, slots=True)
class _Box:
    region: TextRegion
    polygon: Polygon
    height: float
    width: float
    angle: float
    center: tuple[float, float]


@dataclass(frozen=True, slots=True)
class _Place:
    name: str
    confidence: float | None
    page: int
    x: float
    y: float
    width: float
    height: float

    def as_row(self) -> dict[str, TableValue]:
        return {
            "name": self.name,
            "confidence": self.confidence,
            "page": self.page,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


def _shape(points: Sequence[PixelPoint]) -> Polygon | None:
    drawn = Polygon(points)
    shape = drawn if drawn.is_valid else make_valid(drawn)
    if shape.is_empty or not isinstance(shape, Polygon) or shape.area <= 0:
        return None
    return shape


def _rotated_corners(shape: Polygon) -> tuple[tuple[float, float], ...] | None:
    envelope = shape.minimum_rotated_rectangle
    if envelope.is_empty or not isinstance(envelope, Polygon):
        return None
    corners = tuple((float(x), float(y)) for x, y in envelope.exterior.coords[:-1])
    if len(corners) != 4:
        return None
    for x, y in corners:
        if not isfinite(x) or not isfinite(y):
            return None
    return corners


def _sides(corners: Sequence[tuple[float, float]]) -> tuple[float, float]:
    lengths = [
        hypot(
            corners[(index + 1) % 4][0] - corners[index][0],
            corners[(index + 1) % 4][1] - corners[index][1],
        )
        for index in range(4)
    ]
    return max(lengths), min(lengths)


def _long_edge_angle(corners: Sequence[tuple[float, float]]) -> float:
    edges = [
        (
            corners[(index + 1) % 4][0] - corners[index][0],
            corners[(index + 1) % 4][1] - corners[index][1],
        )
        for index in range(4)
    ]
    dx, dy = max(edges, key=lambda edge: hypot(*edge))
    if dx < 0 or (dx == 0 and dy < 0):
        dx, dy = -dx, -dy
    return degrees(atan2(dy, dx))


def _midpoint(corners: Sequence[tuple[float, float]]) -> tuple[float, float]:
    x = sum(point[0] for point in corners) / len(corners)
    y = sum(point[1] for point in corners) / len(corners)
    return x, y


def _measure(region: TextRegion) -> _Box | None:
    shape = _shape(region.polygon)
    if shape is None:
        return None
    corners = _rotated_corners(shape)
    if corners is None:
        return None
    width, height = _sides(corners)
    if height <= 0:
        return None
    return _Box(
        region=region,
        polygon=shape,
        height=height,
        width=width,
        angle=_long_edge_angle(corners),
        center=_midpoint(corners),
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (percentile / 100) * (len(ordered) - 1)
    lower = floor(rank)
    upper = min(lower + 1, len(ordered) - 1)
    share = rank - lower
    return ordered[lower] * (1 - share) + ordered[upper] * share


def _letter_height(boxes: Sequence[_Box]) -> float:
    heights: list[float] = []
    elongated: list[float] = []
    for box in boxes:
        heights.append(box.height)
        if box.width >= _ELONGATED_RATIO * box.height:
            elongated.append(box.height)
    if len(elongated) >= _ELONGATED_FOR_LETTER_HEIGHT:
        return _percentile(elongated, 50.0)
    return _percentile(heights, _LETTER_HEIGHT_PERCENTILE)


def _is_noise(box: _Box, letter_height: float, min_height_ratio: float) -> bool:
    if box.height >= min_height_ratio * letter_height:
        return False
    return box.width / box.height < _SQUARE_RATIO


def _angle_difference(first: float, second: float) -> float:
    difference = abs(first - second) % 180
    if difference > 90:
        return 180 - difference
    return difference


def _comparable_heights(first: _Box, second: _Box) -> bool:
    lower = min(first.height, second.height)
    upper = max(first.height, second.height)
    if upper > _MAX_NEIGHBOUR_HEIGHT * lower:
        return False
    return lower >= _MIN_NEIGHBOUR_HEIGHT * upper


def _average_axis(first: float, second: float) -> tuple[float, float]:
    x = cos(radians(first)) + cos(radians(second))
    y = sin(radians(first)) + sin(radians(second))
    length = hypot(x, y)
    return x / length, y / length


def _interval(
    corners: Sequence[tuple[float, float]], axis: tuple[float, float]
) -> tuple[float, float]:
    projected = [x * axis[0] + y * axis[1] for x, y in corners]
    return min(projected), max(projected)


def _baseline_gap(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
    axis: tuple[float, float],
) -> float:
    one = _interval(first, axis)
    other = _interval(second, axis)
    return max(0.0, max(one[0], other[0]) - min(one[1], other[1]))


def _baseline_offset(first: _Box, second: _Box, axis: tuple[float, float]) -> float:
    # The baseline normal is the axis turned a quarter turn.
    return abs(
        (second.center[0] - first.center[0]) * -axis[1]
        + (second.center[1] - first.center[1]) * axis[0]
    )


def _shares_a_line(
    first: _Box,
    second: _Box,
    first_corners: Sequence[tuple[float, float]],
    second_corners: Sequence[tuple[float, float]],
    *,
    max_angle_degrees: float,
    max_baseline_offset: float,
    max_gap_heights: float,
) -> bool:
    if _angle_difference(first.angle, second.angle) > max_angle_degrees:
        return False
    if not _comparable_heights(first, second):
        return False
    axis = _average_axis(first.angle, second.angle)
    offset = _baseline_offset(first, second, axis)
    if offset > max_baseline_offset * max(first.height, second.height):
        return False
    gap = _baseline_gap(first_corners, second_corners, axis)
    return gap <= max_gap_heights * (first.height + second.height) / 2


def _groups(
    boxes: Sequence[_Box],
    corners: Sequence[Sequence[tuple[float, float]]],
    *,
    max_angle_degrees: float,
    max_baseline_offset: float,
    max_gap_heights: float,
) -> list[list[int]]:
    parent = list(range(len(boxes)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for index, first in enumerate(boxes):
        for other in range(index + 1, len(boxes)):
            if not _shares_a_line(
                first,
                boxes[other],
                corners[index],
                corners[other],
                max_angle_degrees=max_angle_degrees,
                max_baseline_offset=max_baseline_offset,
                max_gap_heights=max_gap_heights,
            ):
                continue
            left, right = root(index), root(other)
            if left != right:
                parent[right] = left

    joined: dict[int, list[int]] = {}
    for index in range(len(boxes)):
        joined.setdefault(root(index), []).append(index)
    return list(joined.values())


def _span_polygon(members: Sequence[_Box]) -> list[PixelPoint] | None:
    union = members[0].polygon
    for box in members[1:]:
        union = union.union(box.polygon)
    if union.is_empty:
        return None
    envelope = union.minimum_rotated_rectangle
    if not isinstance(envelope, Polygon):
        return None
    left, top, right, bottom = union.bounds
    corners = [(float(x), float(y)) for x, y in envelope.exterior.coords[:-1]]
    if any(x < left or x > right or y < top or y > bottom for x, y in corners):
        # A rotated envelope can extend past the source page at its corners.
        hull = union.convex_hull
        if not isinstance(hull, Polygon):
            return None
        corners = [(float(x), float(y)) for x, y in hull.exterior.coords[:-1]]
    if len(corners) < 3:
        return None
    for x, y in corners:
        if not isfinite(x) or not isfinite(y) or x < 0 or y < 0:
            return None
    return corners


def _best_score(members: Sequence[_Box]) -> float | None:
    scores = [box.region.score for box in members if box.region.score is not None]
    if not scores:
        return None
    return max(scores)


def _lowest_point(polygon: Sequence[PixelPoint]) -> tuple[float, float]:
    return min(y for _, y in polygon), min(x for x, _ in polygon)


def prepare_labels(
    regions: Sequence[TextRegion],
    *,
    min_height_ratio: float = _MIN_HEIGHT_RATIO,
    max_gap_heights: float = 1.5,
    max_baseline_offset: float = 0.45,
    max_angle_degrees: float = 12.0,
) -> list[TextRegion]:
    """Drop symbol-sized squares and join the boxes that share one baseline."""
    boxes: list[_Box] = []
    for region in regions:
        box = _measure(region)
        if box is not None:
            boxes.append(box)
    if not boxes:
        return []

    letter_height = _letter_height(boxes)
    kept: list[_Box] = []
    for box in boxes:
        if not _is_noise(box, letter_height, min_height_ratio):
            kept.append(box)
    if not kept:
        return []

    corners = [_rotated_corners(box.polygon) or () for box in kept]
    prepared: list[TextRegion] = []
    for group in _groups(
        kept,
        corners,
        max_angle_degrees=max_angle_degrees,
        max_baseline_offset=max_baseline_offset,
        max_gap_heights=max_gap_heights,
    ):
        members = [kept[index] for index in group]
        if len(members) == 1:
            prepared.append(members[0].region)
            continue
        span = _span_polygon(members)
        if span is None:
            prepared.extend(member.region for member in members)
            continue
        prepared.append(TextRegion(polygon=span, text=None, score=_best_score(members)))

    return sorted(prepared, key=lambda region: _lowest_point(region.polygon))


def filter_readings(
    regions: Sequence[TiffRecognizedRegion],
    *,
    min_confidence: float = 0.4,
    min_letters: int = 3,
) -> list[TiffRecognizedRegion]:
    """Keep the readings that could be the name of a place."""
    kept: list[TiffRecognizedRegion] = []
    for region in regions:
        reading = region.reading
        if reading is None:
            continue
        name = reading.text.strip()
        if not name:
            continue
        confidence = reading.confidence
        if confidence is not None and confidence < min_confidence:
            continue
        letters = 0
        nonspace = 0
        for character in name:
            if character.isalpha():
                letters += 1
            if not character.isspace():
                nonspace += 1
        if letters < min_letters:
            continue
        if letters / nonspace < _NAME_LETTER_SHARE:
            continue
        kept.append(region)
    return kept


def _centroid(shape: Polygon) -> tuple[float, float]:
    point = shape.centroid
    x, y = float(point.x), float(point.y)
    if isfinite(x) and isfinite(y):
        return x, y
    left, bottom, right, top = shape.bounds
    return (left + right) / 2, (bottom + top) / 2


def _bounds_sides(shape: Polygon) -> tuple[float, float]:
    left, bottom, right, top = shape.bounds
    x, y = right - left, top - bottom
    return max(x, y), min(x, y)


def _place(region: TiffRecognizedRegion, page: int) -> _Place | None:
    reading = region.reading
    if reading is None:
        return None
    name = reading.text.strip()
    if _WATER_PREFIX.match(name):
        return None
    name = _SETTLEMENT_PREFIX.sub("", name, count=1).strip()
    if not name:
        return None
    shape = _shape(region.polygon)
    if shape is None:
        return None
    x, y = _centroid(shape)
    corners = _rotated_corners(shape)
    if corners is None:
        width, height = _bounds_sides(shape)
    else:
        width, height = _sides(corners)
    return _Place(
        name=name,
        confidence=reading.confidence,
        page=page,
        x=x,
        y=y,
        width=width,
        height=height,
    )


def places_table(recognized: TiffRecognizedText) -> Table:
    """One row per reading, with where it sits on the page."""
    places: list[_Place] = []
    for region in recognized.regions:
        place = _place(region, int(recognized.window.page))
        if place is not None:
            places.append(place)
    places.sort(key=lambda place: (place.y, place.x, place.name))
    return Table(
        columns=list(_PLACES_COLUMNS), rows=[place.as_row() for place in places]
    )

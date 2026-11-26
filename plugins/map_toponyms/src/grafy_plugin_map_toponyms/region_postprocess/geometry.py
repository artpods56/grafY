"""Measure and join text-region polygons in page pixel space."""

from collections.abc import Sequence
from math import atan2, cos, degrees, floor, hypot, isfinite, radians, sin
from typing import cast
import warnings

from grafy_core.contracts.ocr import PixelPoint, TextRegion
from shapely import (
    Polygon,
    make_valid,  # pyright: ignore[reportUnknownVariableType]
    unary_union,  # pyright: ignore[reportUnknownVariableType]
)
from shapely.geometry.base import BaseGeometry

from grafy_plugin_map_toponyms.region_postprocess.types import (
    PolygonShape,
    RectCorners,
    RegionBox,
)

# Word-like boxes are wider than this many times their height.
_ELONGATED_ASPECT = 2.2
_ELONGATED_SAMPLE = 4
# Heights above this multiple of the median are captions or watermarks.
_HEIGHT_CAP_FACTOR = 2.5
_LETTER_HEIGHT_PERCENTILE = 75.0


def _orient_axis(dx: float, dy: float) -> tuple[float, float]:
    """Point the vector into the right half-plane, or straight up on the y axis."""
    if dx < 0.0 or (dx == 0.0 and dy < 0.0):
        return -dx, -dy
    return dx, dy


def _edge_angle(dx: float, dy: float) -> float:
    oriented_x, oriented_y = _orient_axis(dx, dy)
    return degrees(atan2(oriented_y, oriented_x))


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower = floor(rank)
    upper = min(lower + 1, len(ordered) - 1)
    share = rank - lower
    return ordered[lower] * (1.0 - share) + ordered[upper] * share


def _exterior_points(shape: Polygon) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for x, y in shape.exterior.coords[:-1]:
        points.append((float(x), float(y)))
    return points


def _geometry_parts(shape: BaseGeometry) -> list[BaseGeometry]:
    """Return parts of a MultiPolygon or GeometryCollection."""
    raw = getattr(shape, "geoms", None)
    if raw is None:
        return []
    parts: list[BaseGeometry] = []
    for part in cast(Sequence[object], raw):
        if isinstance(part, BaseGeometry):
            parts.append(part)
    return parts


def _positive_polygons(shape: BaseGeometry) -> list[Polygon]:
    found: list[Polygon] = []
    pending: list[BaseGeometry] = [shape]
    while pending:
        current = pending.pop()
        if isinstance(current, Polygon):
            area = float(current.area)
            if area > 0.0 and isfinite(area):
                found.append(current)
            continue
        pending.extend(_geometry_parts(current))
    return found


def _largest_polygon(shape: BaseGeometry) -> Polygon | None:
    polygons = _positive_polygons(shape)
    if not polygons:
        return None
    return max(polygons, key=lambda polygon: polygon.area)


def _sides(corners: Sequence[tuple[float, float]]) -> tuple[float, float]:
    lengths: list[float] = []
    count = len(corners)
    for index in range(count):
        current = corners[index]
        nxt = corners[(index + 1) % count]
        lengths.append(hypot(nxt[0] - current[0], nxt[1] - current[1]))
    return max(lengths), min(lengths)


def _long_edge(corners: Sequence[tuple[float, float]]) -> tuple[float, float]:
    best_dx = 0.0
    best_dy = 0.0
    best_length = -1.0
    count = len(corners)
    for index in range(count):
        current = corners[index]
        nxt = corners[(index + 1) % count]
        dx = nxt[0] - current[0]
        dy = nxt[1] - current[1]
        length = hypot(dx, dy)
        if length > best_length:
            best_length = length
            best_dx = dx
            best_dy = dy
    return best_dx, best_dy


def _midpoint(corners: Sequence[tuple[float, float]]) -> tuple[float, float]:
    count = len(corners)
    x = sum(point[0] for point in corners) / count
    y = sum(point[1] for point in corners) / count
    return x, y


def _dot(point: tuple[float, float], axis: tuple[float, float]) -> float:
    return point[0] * axis[0] + point[1] * axis[1]


def _text_axis(
    members: Sequence[RegionBox], axis: tuple[float, float] | None
) -> tuple[float, float]:
    if axis is not None:
        return axis
    if members:
        return axis_vector(members[0].angle)
    return (1.0, 0.0)


def sanitize_polygon(points: Sequence[PixelPoint]) -> Polygon | None:
    """Return the largest polygon with positive area."""
    drawn = Polygon(points)
    shape = drawn if drawn.is_valid else make_valid(drawn)
    if shape.is_empty:
        return None
    polygon = _largest_polygon(shape)
    if polygon is None or polygon.area <= 0.0:
        return None
    return polygon


def rotated_corners(shape: Polygon) -> RectCorners | None:
    """Return four finite corners of the minimum rotated rectangle."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=RuntimeWarning,
            module=r"shapely\.constructive",
        )
        envelope = shape.minimum_rotated_rectangle
    if envelope.is_empty or not isinstance(envelope, Polygon):
        return None
    raw = _exterior_points(envelope)
    if len(raw) != 4:
        return None
    for x, y in raw:
        if not isfinite(x) or not isfinite(y):
            return None
    return (raw[0], raw[1], raw[2], raw[3])


def measure_polygon(
    shape: Polygon, *, region: TextRegion, was_merged: bool = False
) -> RegionBox | None:
    """Measure the oriented box of a polygon in page pixels."""
    corners = rotated_corners(shape)
    if corners is None:
        return None
    width, height = _sides(corners)
    if width <= 0.0 or height <= 0.0:
        return None
    angle = _edge_angle(*_long_edge(corners))
    center = _midpoint(corners)
    area = float(shape.area)
    aspect = width / height
    if (
        not isfinite(angle)
        or not isfinite(center[0])
        or not isfinite(center[1])
        or not isfinite(area)
        or area <= 0.0
        or not isfinite(aspect)
    ):
        return None
    return RegionBox(
        region=region,
        polygon=shape,
        corners=corners,
        width=width,
        height=height,
        angle=angle,
        center=center,
        area=area,
        aspect=aspect,
        was_merged=was_merged,
    )


def measure_region(region: TextRegion) -> RegionBox | None:
    """Sanitize a text region and measure its oriented box."""
    shape = sanitize_polygon(region.polygon)
    if shape is None:
        return None
    return measure_polygon(shape, region=region, was_merged=False)


def estimate_letter_height(boxes: Sequence[RegionBox]) -> float:
    """Estimate the typical letter height in pixels."""
    if not boxes:
        return 0.0
    heights: list[float] = []
    elongated: list[float] = []
    for box in boxes:
        heights.append(box.height)
        if box.aspect >= _ELONGATED_ASPECT:
            elongated.append(box.height)
    if len(elongated) >= _ELONGATED_SAMPLE:
        median = _percentile(elongated, 50.0)
        trimmed = [
            height for height in elongated if height <= _HEIGHT_CAP_FACTOR * median
        ]
        if len(trimmed) >= _ELONGATED_SAMPLE:
            return _percentile(trimmed, 50.0)
        return median
    return _percentile(heights, _LETTER_HEIGHT_PERCENTILE)


def angle_difference(first: float, second: float) -> float:
    """Return the smallest undirected angle between two directions, in degrees."""
    difference = abs(first - second) % 180.0
    if difference > 90.0:
        return 180.0 - difference
    return difference


def is_square_box(box: RegionBox, square_aspect_threshold: float) -> bool:
    """Return whether the box is shorter than an elongated word."""
    return box.aspect < square_aspect_threshold


def axis_vector(angle_degrees: float) -> tuple[float, float]:
    """Return the unit vector for an angle in degrees."""
    rad = radians(angle_degrees)
    return cos(rad), sin(rad)


def average_axis(first_angle: float, second_angle: float) -> tuple[float, float]:
    """Average two line directions without cancelling near-vertical text."""
    first_x, first_y = axis_vector(first_angle)
    second_x, second_y = axis_vector(second_angle)
    # A line has no preferred direction. Flip the second vector onto the first
    # half-plane so -85 degrees and +85 degrees meet near 90 degrees.
    if first_x * second_x + first_y * second_y < 0.0:
        second_x = -second_x
        second_y = -second_y
    dx = first_x + second_x
    dy = first_y + second_y
    length = hypot(dx, dy)
    if length == 0.0:
        return _orient_axis(first_x, first_y)
    return _orient_axis(dx / length, dy / length)


def pair_reading_axis(
    first: RegionBox, second: RegionBox, square_aspect_threshold: float
) -> tuple[float, float]:
    """Return the reading direction shared by two boxes."""
    first_elongated = not is_square_box(first, square_aspect_threshold)
    second_elongated = not is_square_box(second, square_aspect_threshold)
    if first_elongated and second_elongated:
        return average_axis(first.angle, second.angle)
    if first_elongated:
        return axis_vector(first.angle)
    if second_elongated:
        return axis_vector(second.angle)
    dx = second.center[0] - first.center[0]
    dy = second.center[1] - first.center[1]
    length = hypot(dx, dy)
    if length == 0.0:
        return axis_vector(first.angle)
    return _orient_axis(dx / length, dy / length)


def project_interval(
    points: Sequence[tuple[float, float]], axis: tuple[float, float]
) -> tuple[float, float]:
    """Return the minimum and maximum projection of points onto an axis."""
    if not points:
        return 0.0, 0.0
    low = _dot(points[0], axis)
    high = low
    for point in points[1:]:
        projected = _dot(point, axis)
        if projected < low:
            low = projected
        elif projected > high:
            high = projected
    return low, high


def projected_thickness(
    points: Sequence[tuple[float, float]], axis: tuple[float, float]
) -> float:
    """Return the extent of points along the axis normal."""
    normal = (-axis[1], axis[0])
    low, high = project_interval(points, normal)
    return high - low


def baseline_gap(
    first_corners: Sequence[tuple[float, float]],
    second_corners: Sequence[tuple[float, float]],
    axis: tuple[float, float],
) -> float:
    """Return the gap between two boxes along an axis, or 0 when they overlap."""
    first_start, first_end = project_interval(first_corners, axis)
    second_start, second_end = project_interval(second_corners, axis)
    return max(0.0, max(first_start, second_start) - min(first_end, second_end))


def baseline_offset(
    first_center: tuple[float, float],
    second_center: tuple[float, float],
    axis: tuple[float, float],
) -> float:
    """Return the perpendicular distance between two centers."""
    dx = second_center[0] - first_center[0]
    dy = second_center[1] - first_center[1]
    return abs(dx * -axis[1] + dy * axis[0])


def merge_polygons_geometry(polygons: Sequence[Polygon]) -> Polygon | None:
    """Union polygons, falling back to the convex hull of a multi-part result."""
    if not polygons:
        return None
    union = unary_union(list(polygons))
    if union.is_empty:
        return None
    if isinstance(union, Polygon) and union.area > 0.0:
        return union
    hull = union.convex_hull
    if isinstance(hull, Polygon) and hull.area > 0.0:
        return hull
    return None


def merge_scores(regions: Sequence[TextRegion]) -> float | None:
    """Return the highest detection score, or None when every score is missing."""
    best: float | None = None
    for region in regions:
        score = region.score
        if score is None:
            continue
        if best is None or score > best:
            best = score
    return best


def merge_texts(
    members: Sequence[RegionBox],
    *,
    axis: tuple[float, float] | None = None,
    separator: str = " ",
) -> str | None:
    """Join member text in reading order, skipping blanks and consecutive repeats."""
    reading = _text_axis(members, axis)

    def projection(box: RegionBox) -> float:
        return _dot(box.center, reading)

    parts: list[str] = []
    for box in sorted(members, key=projection):
        text = box.region.text
        if text is None:
            continue
        stripped = text.strip()
        if not stripped or (parts and parts[-1] == stripped):
            continue
        parts.append(stripped)
    if not parts:
        return None
    return separator.join(parts)


def merge_boxes(
    members: Sequence[RegionBox],
    *,
    axis: tuple[float, float] | None = None,
    text_separator: str = " ",
) -> RegionBox | None:
    """Union member polygons into one measured text region."""
    if not members:
        return None
    merged_poly = merge_polygons_geometry([member.polygon for member in members])
    if merged_poly is None:
        return None
    clamped = clamp_polygon(_exterior_points(merged_poly))
    if clamped is None:
        return None
    score = merge_scores([member.region for member in members])
    reading = axis
    if reading is None:
        corners = rotated_corners(merged_poly)
        if corners is None:
            return None
        reading = axis_vector(_edge_angle(*_long_edge(corners)))
    text = merge_texts(members, axis=reading, separator=text_separator)
    merged_region = TextRegion(polygon=clamped, text=text, score=score)
    return measure_polygon(merged_poly, region=merged_region, was_merged=True)


def clamp_polygon(
    points: Sequence[tuple[float, float]],
    *,
    max_x: float | None = None,
    max_y: float | None = None,
) -> list[PixelPoint] | None:
    """Clamp coordinates onto the page and drop a collapsed ring."""
    if max_x is not None and (not isfinite(max_x) or max_x < 0.0):
        return None
    if max_y is not None and (not isfinite(max_y) or max_y < 0.0):
        return None
    clamped: list[PixelPoint] = []
    for x, y in points:
        cx = float(x)
        cy = float(y)
        if not isfinite(cx) or not isfinite(cy):
            return None
        if cx < 0.0:
            cx = 0.0
        if cy < 0.0:
            cy = 0.0
        if max_x is not None and cx > max_x:
            cx = max_x
        if max_y is not None and cy > max_y:
            cy = max_y
        point = (cx, cy)
        if clamped and clamped[-1] == point:
            continue
        clamped.append(point)
    if len(clamped) >= 2 and clamped[-1] == clamped[0]:
        clamped.pop()
    if len(clamped) < 3:
        return None
    if Polygon(clamped).area <= 0.0:
        return None
    return clamped


def pad_polygon_oriented(
    points: Sequence[tuple[float, float]],
    *,
    center: tuple[float, float],
    angle: float,
    width: float,
    height: float,
    pad_along_px: float,
    pad_across_px: float,
) -> list[tuple[float, float]]:
    """Scale a polygon about its center along and across its reading axis."""
    if (pad_along_px == 0.0 and pad_across_px == 0.0) or width <= 0.0 or height <= 0.0:
        return list(points)
    axis_x, axis_y = axis_vector(angle)
    normal_x = -axis_y
    normal_y = axis_x
    along_scale = (width + 2.0 * pad_along_px) / width
    across_scale = (height + 2.0 * pad_across_px) / height
    center_x, center_y = center
    padded: list[tuple[float, float]] = []
    for x, y in points:
        dx = x - center_x
        dy = y - center_y
        along = (dx * axis_x + dy * axis_y) * along_scale
        across = (dx * normal_x + dy * normal_y) * across_scale
        padded.append(
            (
                center_x + along * axis_x + across * normal_x,
                center_y + along * axis_y + across * normal_y,
            )
        )
    return padded


def _hull_points(box: RegionBox) -> list[tuple[float, float]]:
    hull = box.polygon.convex_hull
    if isinstance(hull, Polygon):
        points = _exterior_points(hull)
        if len(points) >= 3:
            return points
    return list(box.corners)


def _simplified_points(box: RegionBox, tolerance: float) -> list[tuple[float, float]]:
    simplified = box.polygon.simplify(tolerance, preserve_topology=True)
    if isinstance(simplified, Polygon):
        points = _exterior_points(simplified)
        if len(points) >= 3:
            return points
    return _exterior_points(box.polygon)


def _polygon_points(
    box: RegionBox, polygon_shape: PolygonShape, simplify_tolerance_px: float
) -> list[tuple[float, float]]:
    if polygon_shape == "oriented_rect":
        # Rotated corners can sit slightly outside polygon.bounds.
        # clamp_polygon applies the page limits.
        return list(box.corners)
    if polygon_shape == "convex_hull":
        return _hull_points(box)
    if polygon_shape == "keep_original":
        if box.was_merged:
            return list(box.corners)
        return _exterior_points(box.polygon)
    return _simplified_points(box, simplify_tolerance_px)


def shape_polygon(
    box: RegionBox,
    *,
    polygon_shape: PolygonShape,
    pad_along_px: float = 0.0,
    pad_across_px: float = 0.0,
    simplify_tolerance_px: float = 1.5,
    max_x: float | None = None,
    max_y: float | None = None,
) -> list[PixelPoint] | None:
    """Build the output ring for one measured box."""
    points = _polygon_points(box, polygon_shape, simplify_tolerance_px)
    if pad_along_px > 0.0 or pad_across_px > 0.0:
        points = pad_polygon_oriented(
            points,
            center=box.center,
            angle=box.angle,
            width=box.width,
            height=box.height,
            pad_along_px=pad_along_px,
            pad_across_px=pad_across_px,
        )
    return clamp_polygon(points, max_x=max_x, max_y=max_y)


def reading_order_key(region: TextRegion) -> tuple[float, float]:
    """Sort key of the smallest y, then the smallest x."""
    return (
        min(y for _, y in region.polygon),
        min(x for x, _ in region.polygon),
    )

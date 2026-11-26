"""Join text boxes that share a reading baseline."""

from collections.abc import Sequence
from dataclasses import dataclass

from shapely import STRtree
from shapely.geometry import box

from grafy_plugin_map_toponyms.region_postprocess.geometry import (
    angle_difference,
    baseline_gap,
    baseline_offset,
    is_square_box,
    merge_boxes,
    pair_reading_axis,
    projected_thickness,
)
from grafy_plugin_map_toponyms.region_postprocess.types import (
    PostprocessOptions,
    RegionBox,
)


@dataclass(frozen=True, slots=True)
class BaselineJoinResult:
    """Boxes left after baseline joins, and how many merges were performed."""

    boxes: list[RegionBox]
    spans_joined: int


@dataclass(frozen=True, slots=True)
class _Span:
    box: RegionBox
    member_count: int
    max_member_height: float


@dataclass(frozen=True, order=True, slots=True)
class _Candidate:
    gap: float
    left: int
    right: int
    axis: tuple[float, float]


def join_baselines(
    boxes: Sequence[RegionBox], options: PostprocessOptions
) -> BaselineJoinResult:
    """Merge collinear fragments on one baseline and leave stacked lines apart."""
    if not options.join_baselines or len(boxes) <= 1 or options.max_gap_heights <= 0:
        return BaselineJoinResult(boxes=list(boxes), spans_joined=0)

    active = [
        _Span(box=item, member_count=1, max_member_height=item.height) for item in boxes
    ]
    # Each accepted merge removes one span, so this many passes is the maximum.
    for _ in range(len(boxes) - 1):
        joined = _join_closest(active, options)
        if joined is None:
            break
        active = joined
    return BaselineJoinResult(
        boxes=[span.box for span in active],
        spans_joined=len(boxes) - len(active),
    )


def _can_join(
    first: RegionBox, second: RegionBox, options: PostprocessOptions
) -> tuple[float, tuple[float, float]] | None:
    first_square = is_square_box(first, options.square_aspect_threshold)
    second_square = is_square_box(second, options.square_aspect_threshold)
    if not options.allow_short_fragment_joining and (first_square or second_square):
        return None
    if not first_square and not second_square:
        difference = angle_difference(first.angle, second.angle)
        if difference > options.max_angle_degrees:
            return None

    axis = pair_reading_axis(first, second, options.square_aspect_threshold)
    first_height = projected_thickness(first.corners, axis)
    second_height = projected_thickness(second.corners, axis)
    if first_height <= 0 or second_height <= 0:
        return None
    shorter = min(first_height, second_height)
    taller = max(first_height, second_height)
    if shorter / taller < options.min_neighbour_height_ratio:
        return None

    # Scale baseline tolerance to the shorter box so a tall two-line box cannot
    # pull in an off-center single-line settlement sitting near one of its corners.
    offset = baseline_offset(first.center, second.center, axis)
    if offset > options.max_baseline_offset * shorter:
        return None

    gap = baseline_gap(first.corners, second.corners, axis)
    reference_height = (first_height + second_height) / 2.0
    if gap > options.max_gap_heights * reference_height:
        return None
    return gap, axis


def _join_closest(
    active: Sequence[_Span], options: PostprocessOptions
) -> list[_Span] | None:
    candidates = _candidates(active, options)
    if not candidates:
        return None
    candidates.sort()
    consumed: set[int] = set()
    replacements: dict[int, _Span] = {}
    for candidate in candidates:
        if candidate.left in consumed or candidate.right in consumed:
            continue
        merged = _merge_span(
            active[candidate.left],
            active[candidate.right],
            candidate.axis,
            options,
        )
        if merged is None:
            continue
        consumed.add(candidate.left)
        consumed.add(candidate.right)
        replacements[candidate.left] = merged
    if not replacements:
        return None
    return _rebuild(active, replacements, consumed)


def _candidates(
    active: Sequence[_Span], options: PostprocessOptions
) -> list[_Candidate]:
    tree = STRtree([span.box.polygon for span in active])
    found: list[_Candidate] = []
    ratio = max(options.min_neighbour_height_ratio, 0.1)
    max_neighbor_scale = 0.5 * (1.0 + 1.0 / ratio)
    for index, span in enumerate(active):
        radius = (
            options.max_gap_heights * span.box.height * max_neighbor_scale
            + span.box.height / ratio
        )
        minx, miny, maxx, maxy = span.box.polygon.bounds
        nearby = box(minx - radius, miny - radius, maxx + radius, maxy + radius)
        for hit in tree.query(nearby):
            other = int(hit)
            if other <= index:
                continue
            neighbour = active[other]
            members = span.member_count + neighbour.member_count
            if members > options.max_chain_members:
                continue
            compatible = _can_join(span.box, neighbour.box, options)
            if compatible is None:
                continue
            gap, axis = compatible
            found.append(_Candidate(gap=gap, left=index, right=other, axis=axis))
    return found


def _merge_span(
    left: _Span,
    right: _Span,
    axis: tuple[float, float],
    options: PostprocessOptions,
) -> _Span | None:
    merged = merge_boxes(
        [left.box, right.box],
        axis=axis,
        text_separator=options.merge_text_separator,
    )
    if merged is None:
        return None
    tallest = max(left.max_member_height, right.max_member_height)
    left_square = is_square_box(left.box, options.square_aspect_threshold)
    right_square = is_square_box(right.box, options.square_aspect_threshold)
    if left_square != right_square:
        anchor_height = (
            right.max_member_height if left_square else left.max_member_height
        )
    else:
        anchor_height = tallest
    if merged.height > options.max_merged_height_ratio * anchor_height:
        return None
    return _Span(
        box=merged,
        member_count=left.member_count + right.member_count,
        max_member_height=tallest,
    )


def _rebuild(
    active: Sequence[_Span],
    replacements: dict[int, _Span],
    consumed: set[int],
) -> list[_Span]:
    rebuilt: list[_Span] = []
    for index, span in enumerate(active):
        replacement = replacements.get(index)
        if replacement is not None:
            rebuilt.append(replacement)
            continue
        if index in consumed:
            continue
        rebuilt.append(span)
    return rebuilt

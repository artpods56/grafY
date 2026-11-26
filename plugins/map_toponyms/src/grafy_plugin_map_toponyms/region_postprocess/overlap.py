"""Collapse duplicate and overlapping text boxes from a map OCR pass."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, assert_never

from grafy_core.contracts.ocr import TextRegion
from shapely import STRtree

from grafy_plugin_map_toponyms.region_postprocess.geometry import (
    angle_difference,
    is_square_box,
    merge_boxes,
    pair_reading_axis,
)
from grafy_plugin_map_toponyms.region_postprocess.types import (
    PostprocessOptions,
    RegionBox,
)

type _PairMode = Literal["merge", "partial"]


@dataclass(frozen=True, slots=True)
class OverlapResult:
    """Boxes kept after overlap resolution, and regions suppressed without a merge.

    `dropped` holds duplicates and contained inner boxes discarded by `keep_best`
    or by the nested-suppression phase of `smart`. A box absorbed into a combined
    box is not listed here.
    """

    kept: list[RegionBox]
    dropped: list[TextRegion]
    overlaps_resolved: int


def resolve_overlaps(
    boxes: Sequence[RegionBox], options: PostprocessOptions
) -> OverlapResult:
    """Suppress duplicates and merge compatible overlapping fragments."""
    if not options.resolve_overlaps or len(boxes) <= 1:
        return OverlapResult(kept=list(boxes), dropped=[], overlaps_resolved=0)

    mode = options.overlap_mode
    if mode == "keep_best":
        kept, dropped = _keep_best(boxes, options)
    elif mode == "merge":
        kept = _merge_until_stable(boxes, options, mode="merge")
        dropped: list[TextRegion] = []
    elif mode == "smart":
        kept, dropped = _resolve_smart(boxes, options)
    else:
        assert_never(mode)

    return OverlapResult(
        kept=kept,
        dropped=dropped,
        overlaps_resolved=len(boxes) - len(kept),
    )


def _angles_compatible(a: RegionBox, b: RegionBox, options: PostprocessOptions) -> bool:
    """True when the boxes may belong to one label.

    A near-square fragment has no reliable reading direction, so it may join a
    word at any angle. Two elongated labels must lie along nearly the same
    direction. A river name crossing a settlement name stays untouched.
    """
    if is_square_box(a, options.square_aspect_threshold) or is_square_box(
        b, options.square_aspect_threshold
    ):
        return True
    return angle_difference(a.angle, b.angle) <= options.overlap_max_angle_degrees


def _detection_score(box: RegionBox) -> float:
    if box.region.score is None:
        return -1.0
    return box.region.score


def _iou_and_containment(a: RegionBox, b: RegionBox) -> tuple[float, float] | None:
    """Return IoU and intersection / min(area) when the polygons actually overlap."""
    intersection_area = a.polygon.intersection(b.polygon).area
    smaller = min(a.area, b.area)
    if intersection_area <= 0 or smaller <= 0:
        return None
    union = a.area + b.area - intersection_area
    iou = intersection_area / union if union > 0 else 0.0
    return iou, intersection_area / smaller


def _later_indices(
    tree: STRtree, box: RegionBox, index: int, skipped: set[int]
) -> list[int]:
    found: list[int] = []
    for hit in tree.query(box.polygon):
        other_index = int(hit)
        if other_index <= index or other_index in skipped:
            continue
        found.append(other_index)
    return found


def _keep_best(
    boxes: Sequence[RegionBox], options: PostprocessOptions
) -> tuple[list[RegionBox], list[TextRegion]]:
    """Non-maximum suppression. The higher score wins, then the larger area."""
    ranked = sorted(
        boxes,
        key=lambda box: (_detection_score(box), box.area),
        reverse=True,
    )
    tree = STRtree([box.polygon for box in ranked])
    suppressed: set[int] = set()
    kept: list[RegionBox] = []
    dropped: list[TextRegion] = []
    for index, item in enumerate(ranked):
        if index in suppressed:
            continue
        kept.append(item)
        for other_index in _later_indices(tree, item, index, suppressed):
            other = ranked[other_index]
            if not _nms_suppresses(item, other, options):
                continue
            suppressed.add(other_index)
            dropped.append(other.region)
    return kept, dropped


def _nms_suppresses(
    item: RegionBox, other: RegionBox, options: PostprocessOptions
) -> bool:
    if not _angles_compatible(item, other, options):
        return False
    measured = _iou_and_containment(item, other)
    if measured is None:
        return False
    iou, containment = measured
    return (
        iou >= options.merge_iou_threshold
        or containment >= options.containment_threshold
    )


def _resolve_smart(
    boxes: Sequence[RegionBox], options: PostprocessOptions
) -> tuple[list[RegionBox], list[TextRegion]]:
    """Drop nested copies, then merge partial overlaps that pass the height guard."""
    remaining, dropped = _suppress_nested(boxes, options)
    return _merge_until_stable(remaining, options, mode="partial"), dropped


def _suppress_nested(
    boxes: Sequence[RegionBox], options: PostprocessOptions
) -> tuple[list[RegionBox], list[TextRegion]]:
    """Drop a box wholly inside a larger box of the same label.

    Area wins over score so the enclosing word survives and the inner fragment
    is the one recorded in `dropped`.
    """
    ranked = sorted(
        boxes,
        key=lambda box: (box.area, _detection_score(box)),
        reverse=True,
    )
    tree = STRtree([box.polygon for box in ranked])
    suppressed: set[int] = set()
    kept: list[RegionBox] = []
    dropped: list[TextRegion] = []
    for index, item in enumerate(ranked):
        if index in suppressed:
            continue
        kept.append(item)
        for other_index in _later_indices(tree, item, index, suppressed):
            other = ranked[other_index]
            if not _is_contained_inner(item, other, options):
                continue
            suppressed.add(other_index)
            dropped.append(other.region)
    return kept, dropped


def _is_contained_inner(
    item: RegionBox, other: RegionBox, options: PostprocessOptions
) -> bool:
    if not _is_redundant_inner(item, other):
        return False
    if not _angles_compatible(item, other, options):
        return False
    if other.area <= 0:
        return False
    intersection_area = item.polygon.intersection(other.polygon).area
    return intersection_area / other.area >= options.containment_threshold


def _is_redundant_inner(item: RegionBox, other: RegionBox) -> bool:
    if other.width > item.width * 1.05:
        return False
    if other.area < item.area:
        return True
    if other.area > item.area:
        return False
    return _detection_score(other) < _detection_score(item)


def _merge_until_stable(
    boxes: Sequence[RegionBox],
    options: PostprocessOptions,
    *,
    mode: _PairMode,
) -> list[RegionBox]:
    """Greedily merge disjoint compatible pairs per pass until stable.

    A chain such as `ёв` + `о` + `ая` collapses across passes. Each pass
    rebuilds the spatial index once and applies every non-conflicting merge
    in descending overlap order, keeping the height guard intact at every step.
    """
    active = list(boxes)
    for _ in range(max(1, len(active))):
        merged_pass = _merge_pass(active, options, mode=mode)
        if merged_pass is None:
            return active
        active = merged_pass
    return active


def _merge_pass(
    boxes: Sequence[RegionBox],
    options: PostprocessOptions,
    *,
    mode: _PairMode,
) -> list[RegionBox] | None:
    if len(boxes) < 2:
        return None
    tree = STRtree([box.polygon for box in boxes])
    candidates: list[tuple[tuple[float, float], int, int, RegionBox]] = []
    skipped: set[int] = set()
    for index, item in enumerate(boxes):
        for other_index in _later_indices(tree, item, index, skipped):
            merged = _try_merge(item, boxes[other_index], options, mode=mode)
            if merged is None:
                continue
            rank, combined = merged
            candidates.append((rank, index, other_index, combined))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (entry[0], -entry[1], -entry[2]), reverse=True)
    consumed: set[int] = set()
    replacements: dict[int, RegionBox] = {}
    for _, left, right, combined in candidates:
        if left in consumed or right in consumed:
            continue
        consumed.add(left)
        consumed.add(right)
        replacements[left] = combined
    rebuilt: list[RegionBox] = []
    for index, box in enumerate(boxes):
        replacement = replacements.get(index)
        if replacement is not None:
            rebuilt.append(replacement)
            continue
        if index in consumed:
            continue
        rebuilt.append(box)
    return rebuilt


def _try_merge(
    a: RegionBox,
    b: RegionBox,
    options: PostprocessOptions,
    *,
    mode: _PairMode,
) -> tuple[tuple[float, float], RegionBox] | None:
    if not _angles_compatible(a, b, options):
        return None
    measured = _iou_and_containment(a, b)
    if measured is None:
        return None
    iou, containment = measured
    if not _overlap_qualifies(iou, containment, options, mode=mode):
        return None
    merged = merge_boxes(
        [a, b],
        axis=pair_reading_axis(a, b, options.square_aspect_threshold),
        text_separator=options.merge_text_separator,
    )
    if merged is None:
        return None
    # Touching descenders of two stacked lines must not fuse them vertically.
    if merged.height > options.overlap_max_height_growth * max(a.height, b.height):
        return None
    return _pair_rank(iou, containment, mode), merged


def _overlap_qualifies(
    iou: float,
    containment: float,
    options: PostprocessOptions,
    *,
    mode: _PairMode,
) -> bool:
    if iou >= options.merge_iou_threshold:
        return True
    if mode == "merge" and containment >= options.containment_threshold:
        return True
    return containment >= options.partial_containment_merge_threshold


def _pair_rank(iou: float, containment: float, mode: _PairMode) -> tuple[float, float]:
    if mode == "partial":
        return (containment, iou)
    return (max(iou, containment), containment)

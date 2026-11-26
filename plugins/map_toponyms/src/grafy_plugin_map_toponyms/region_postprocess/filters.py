"""Score, speck, watermark, and small-noise filters for TIFF text regions."""

from collections.abc import Sequence
from dataclasses import dataclass

from grafy_core.contracts.ocr import TextRegion

from grafy_plugin_map_toponyms.region_postprocess.geometry import (
    estimate_letter_height,
    measure_region,
)
from grafy_plugin_map_toponyms.region_postprocess.types import (
    PostprocessOptions,
    RegionBox,
)


@dataclass(frozen=True, slots=True)
class PrefilterResult:
    """Regions left after sanitizing and the pre-join size filters."""

    kept: list[RegionBox]
    dropped: list[TextRegion]
    letter_height: float
    invalid_dropped: int
    score_dropped: int
    outliers_dropped: int
    micro_specks_dropped: int


@dataclass(frozen=True, slots=True)
class NoiseFilterResult:
    """Regions left after the post-join small-noise filter."""

    kept: list[RegionBox]
    dropped: list[TextRegion]
    noise_dropped: int


def _measured_regions(regions: Sequence[TextRegion]) -> tuple[list[RegionBox], int]:
    boxes: list[RegionBox] = []
    invalid_dropped = 0
    for region in regions:
        box = measure_region(region)
        if box is None:
            invalid_dropped += 1
            continue
        boxes.append(box)
    return boxes, invalid_dropped


def _without_low_scores(
    boxes: Sequence[RegionBox], min_score: float
) -> tuple[list[RegionBox], list[TextRegion]]:
    if min_score <= 0:
        return list(boxes), []
    kept: list[RegionBox] = []
    dropped: list[TextRegion] = []
    for box in boxes:
        score = box.region.score
        if score is not None and score < min_score:
            dropped.append(box.region)
            continue
        kept.append(box)
    return kept, dropped


def _without_micro_specks(
    boxes: Sequence[RegionBox], micro_speck_area_px: float
) -> tuple[list[RegionBox], list[TextRegion]]:
    if micro_speck_area_px <= 0:
        return list(boxes), []
    kept: list[RegionBox] = []
    dropped: list[TextRegion] = []
    for box in boxes:
        if box.area < micro_speck_area_px:
            dropped.append(box.region)
            continue
        kept.append(box)
    return kept, dropped


def _exceeds_size_cap(
    box: RegionBox, *, letter_height: float, options: PostprocessOptions
) -> bool:
    too_tall_for_letters = (
        letter_height > 0
        and options.max_height_ratio > 0
        and box.height > options.max_height_ratio * letter_height
    )
    if too_tall_for_letters:
        return True
    if options.max_height_px > 0 and box.height > options.max_height_px:
        return True
    return options.max_area_px > 0 and box.area > options.max_area_px


def _without_large_outliers(
    boxes: Sequence[RegionBox],
    *,
    letter_height: float,
    options: PostprocessOptions,
) -> tuple[list[RegionBox], list[TextRegion]]:
    if not options.drop_large_outliers:
        return list(boxes), []
    kept: list[RegionBox] = []
    dropped: list[TextRegion] = []
    for box in boxes:
        if _exceeds_size_cap(box, letter_height=letter_height, options=options):
            dropped.append(box.region)
            continue
        kept.append(box)
    return kept, dropped


def prefilter_regions(
    regions: Sequence[TextRegion], options: PostprocessOptions
) -> PrefilterResult:
    """Drop degenerate, low-score, speck, and oversized regions.

    Micro-specks are removed before the letter-height estimate so dust does
    not set the scale. When watermarks are removed, the height is estimated
    again from the boxes that remain.
    """
    kept, invalid_dropped = _measured_regions(regions)
    kept, score_dropped = _without_low_scores(kept, options.min_score)
    kept, speck_dropped = _without_micro_specks(kept, options.micro_speck_area_px)
    letter_height = estimate_letter_height(kept)
    kept, outlier_dropped = _without_large_outliers(
        kept, letter_height=letter_height, options=options
    )
    if outlier_dropped and kept:
        letter_height = estimate_letter_height(kept)
    return PrefilterResult(
        kept=kept,
        dropped=[*score_dropped, *speck_dropped, *outlier_dropped],
        letter_height=letter_height,
        invalid_dropped=invalid_dropped,
        score_dropped=len(score_dropped),
        outliers_dropped=len(outlier_dropped),
        micro_specks_dropped=len(speck_dropped),
    )


def _is_below_absolute_minimum(box: RegionBox, options: PostprocessOptions) -> bool:
    if options.min_width_px > 0 and box.width < options.min_width_px:
        return True
    if options.min_height_px > 0 and box.height < options.min_height_px:
        return True
    return options.min_area_px > 0 and box.area < options.min_area_px


def _is_short_noise(
    box: RegionBox, *, letter_height: float, options: PostprocessOptions
) -> bool:
    if letter_height <= 0 or options.min_height_ratio <= 0:
        return False
    if box.height >= options.min_height_ratio * letter_height:
        return False
    if options.drop_elongated_small:
        return True
    return box.aspect < options.noise_square_aspect


def filter_small_noise(
    boxes: Sequence[RegionBox],
    *,
    letter_height: float,
    options: PostprocessOptions,
) -> NoiseFilterResult:
    """Drop map symbols that are still small after words have been joined.

    Short boxes are noise. With ``drop_elongated_small`` off, a short box is
    kept when its aspect is at least ``noise_square_aspect``, so a thin label
    survives and a square symbol does not.
    """
    if not options.drop_small_noise:
        return NoiseFilterResult(kept=list(boxes), dropped=[], noise_dropped=0)
    kept: list[RegionBox] = []
    dropped: list[TextRegion] = []
    for box in boxes:
        if _is_below_absolute_minimum(box, options) or _is_short_noise(
            box, letter_height=letter_height, options=options
        ):
            dropped.append(box.region)
            continue
        kept.append(box)
    return NoiseFilterResult(kept=kept, dropped=dropped, noise_dropped=len(dropped))

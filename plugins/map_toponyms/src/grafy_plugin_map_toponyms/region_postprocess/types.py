"""Shared data structures and options for TIFF text region postprocessing."""

from dataclasses import dataclass
from typing import Literal

from grafy_core.contracts.ocr import TextRegion
from shapely import Polygon

type OverlapMode = Literal["smart", "merge", "keep_best"]
type PostprocessPreset = Literal["balanced", "conservative", "aggressive", "custom"]
type PolygonShape = Literal[
    "oriented_rect", "convex_hull", "keep_original", "simplified"
]
type RectCorners = tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]


@dataclass(frozen=True, slots=True)
class RegionBox:
    """A sanitized text region together with its oriented geometry measurements."""

    region: TextRegion
    polygon: Polygon
    corners: RectCorners
    width: float
    height: float
    angle: float
    center: tuple[float, float]
    area: float
    aspect: float
    was_merged: bool = False


@dataclass(frozen=True, slots=True)
class PostprocessOptions:
    """Tweakable parameters controlling the multi-stage postprocessing pipeline."""

    # Stage 2: Score, giant watermark outlier, and micro-speck pre-filters.
    min_score: float = 0.0
    drop_large_outliers: bool = True
    max_height_ratio: float = 2.5
    max_height_px: float = 0.0
    max_area_px: float = 0.0
    micro_speck_area_px: float = 16.0

    # Stage 3: Smart overlap, duplicate, and nested-box resolution.
    resolve_overlaps: bool = True
    overlap_mode: OverlapMode = "smart"
    merge_iou_threshold: float = 0.25
    containment_threshold: float = 0.80
    partial_containment_merge_threshold: float = 0.45
    overlap_max_angle_degrees: float = 25.0
    overlap_max_height_growth: float = 1.45

    # Stage 4: Baseline / collinear word & prefix joining.
    join_baselines: bool = True
    max_gap_heights: float = 1.2
    max_baseline_offset: float = 0.40
    max_angle_degrees: float = 15.0
    min_neighbour_height_ratio: float = 0.55
    max_merged_height_ratio: float = 1.45
    square_aspect_threshold: float = 1.5
    allow_short_fragment_joining: bool = True
    max_chain_members: int = 8

    # Stage 5: Post-join small noise / map-symbol filter.
    drop_small_noise: bool = True
    min_height_ratio: float = 0.55
    drop_elongated_small: bool = False
    noise_square_aspect: float = 2.0
    min_width_px: float = 0.0
    min_height_px: float = 0.0
    min_area_px: float = 0.0

    # Stage 6: Output geometry normalization, padding, and text joining.
    polygon_shape: PolygonShape = "keep_original"
    pad_along_px: float = 0.0
    pad_across_px: float = 0.0
    simplify_tolerance_px: float = 1.5
    merge_text_separator: str = " "


def preset_options(
    preset: Literal["balanced", "conservative", "aggressive"],
    *,
    polygon_shape: PolygonShape = "keep_original",
    pad_along_px: float = 0.0,
    pad_across_px: float = 0.0,
    simplify_tolerance_px: float = 1.5,
    merge_text_separator: str = " ",
) -> PostprocessOptions:
    """Return tuned pipeline options for a named preset."""
    if preset == "conservative":
        return PostprocessOptions(
            drop_large_outliers=True,
            max_height_ratio=2.5,
            resolve_overlaps=True,
            overlap_mode="keep_best",
            merge_iou_threshold=0.35,
            containment_threshold=0.85,
            join_baselines=True,
            max_gap_heights=0.75,
            max_baseline_offset=0.30,
            drop_small_noise=True,
            min_height_ratio=0.45,
            drop_elongated_small=False,
            polygon_shape=polygon_shape,
            pad_along_px=pad_along_px,
            pad_across_px=pad_across_px,
            simplify_tolerance_px=simplify_tolerance_px,
            merge_text_separator=merge_text_separator,
        )
    if preset == "aggressive":
        return PostprocessOptions(
            drop_large_outliers=True,
            max_height_ratio=2.1,
            resolve_overlaps=True,
            overlap_mode="smart",
            merge_iou_threshold=0.20,
            containment_threshold=0.75,
            join_baselines=True,
            max_gap_heights=1.5,
            max_baseline_offset=0.40,
            drop_small_noise=True,
            min_height_ratio=0.60,
            drop_elongated_small=True,
            polygon_shape=polygon_shape,
            pad_along_px=pad_along_px,
            pad_across_px=pad_across_px,
            simplify_tolerance_px=simplify_tolerance_px,
            merge_text_separator=merge_text_separator,
        )
    return PostprocessOptions(
        drop_large_outliers=True,
        max_height_ratio=2.3,
        resolve_overlaps=True,
        overlap_mode="smart",
        merge_iou_threshold=0.25,
        containment_threshold=0.80,
        join_baselines=True,
        max_gap_heights=1.2,
        max_baseline_offset=0.35,
        drop_small_noise=True,
        min_height_ratio=0.55,
        drop_elongated_small=False,
        polygon_shape=polygon_shape,
        pad_along_px=pad_along_px,
        pad_across_px=pad_across_px,
        simplify_tolerance_px=simplify_tolerance_px,
        merge_text_separator=merge_text_separator,
    )


@dataclass(frozen=True, slots=True)
class PostprocessStats:
    """Per-stage summary counts recorded in execution metadata."""

    input_regions: int
    invalid_dropped: int
    score_dropped: int
    outliers_dropped: int
    micro_specks_dropped: int
    overlaps_resolved: int
    spans_joined: int
    noise_dropped: int
    output_regions: int
    estimated_letter_height: float

    def to_metadata(self) -> dict[str, int | float]:
        return {
            "input_regions": self.input_regions,
            "invalid_dropped": self.invalid_dropped,
            "score_dropped": self.score_dropped,
            "outliers_dropped": self.outliers_dropped,
            "micro_specks_dropped": self.micro_specks_dropped,
            "overlaps_resolved": self.overlaps_resolved,
            "spans_joined": self.spans_joined,
            "noise_dropped": self.noise_dropped,
            "output_regions": self.output_regions,
            "estimated_letter_height": round(self.estimated_letter_height, 2),
        }


@dataclass(frozen=True, slots=True)
class PostprocessResult:
    """Cleaned regions, dropped regions for visual inspection, and stage metrics."""

    regions: list[TextRegion]
    dropped: list[TextRegion]
    stats: PostprocessStats

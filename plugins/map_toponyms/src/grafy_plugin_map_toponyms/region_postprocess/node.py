"""Grafy operator that postprocesses detected TIFF text regions."""

from typing import final, override

from pydantic import Field

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import (
    field_ui,
    validate_config_ui_schema,
    when_all,
    when_field_eq,
    when_field_truthy,
)
from grafy_core.contracts.ocr import TiffPageOpener
from grafy_core.nodes import Node, NodeExecutionContext

from grafy_plugin_map_toponyms.declaration import MAP_TOPONYMS
from grafy_plugin_map_toponyms.region_postprocess.pipeline import postprocess_regions
from grafy_plugin_map_toponyms.region_postprocess.types import (
    OverlapMode,
    PolygonShape,
    PostprocessOptions,
    PostprocessPreset,
    preset_options,
)
from grafy_plugin_map_toponyms.text_regions import TiffTextRegions

_OUTLIERS = "Outliers & Score"
_OVERLAP = "Overlap Merging"
_BASELINE = "Baseline Joining"
_NOISE = "Small Noise Filter"

_IS_CUSTOM = when_field_eq("preset", "custom")


class PostprocessRegionsConfig(NodeConfig):
    # Top-level controls shown by default on the node card.
    preset: PostprocessPreset = Field(
        default="balanced",
        title="Preset",
        description=(
            "Balanced handles most historical maps. Conservative keeps dense "
            "labels separate; Aggressive drops watermarks and thin tree rows; "
            "Custom exposes every stage parameter."
        ),
        json_schema_extra=field_ui(
            widget="segmented",
            enum_labels={
                "balanced": "Balanced",
                "conservative": "Conservative",
                "aggressive": "Aggressive",
                "custom": "Custom",
            },
        ),
    )
    polygon_shape: PolygonShape = Field(
        default="keep_original",
        title="Polygon shape",
        json_schema_extra=field_ui(
            widget="segmented",
            enum_labels={
                "keep_original": "Keep original",
                "oriented_rect": "Oriented rect",
                "convex_hull": "Convex hull",
                "simplified": "Simplified",
            },
        ),
    )

    # Custom-mode stage groups (primary knobs only; micro-knobs live in Advanced).
    drop_large_outliers: bool = Field(
        default=True,
        title="Drop large outliers",
        json_schema_extra=field_ui(
            group=_OUTLIERS, widget="switch", visible_when=_IS_CUSTOM
        ),
    )
    max_height_ratio: float = Field(
        default=2.3,
        ge=0,
        le=20,
        title="Maximum height ratio",
        json_schema_extra=field_ui(
            group=_OUTLIERS,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_large_outliers")),
        ),
    )
    min_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        title="Minimum score",
        json_schema_extra=field_ui(group=_OUTLIERS, visible_when=_IS_CUSTOM),
    )

    resolve_overlaps: bool = Field(
        default=True,
        title="Resolve overlaps",
        json_schema_extra=field_ui(
            group=_OVERLAP, widget="switch", visible_when=_IS_CUSTOM
        ),
    )
    overlap_mode: OverlapMode = Field(
        default="smart",
        title="Overlap mode",
        json_schema_extra=field_ui(
            group=_OVERLAP,
            widget="segmented",
            enum_labels={"smart": "Smart", "merge": "Merge", "keep_best": "Keep best"},
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("resolve_overlaps")),
        ),
    )
    merge_iou_threshold: float = Field(
        default=0.25,
        ge=0,
        le=1,
        title="Merge IoU threshold",
        json_schema_extra=field_ui(
            group=_OVERLAP,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("resolve_overlaps")),
        ),
    )
    containment_threshold: float = Field(
        default=0.80,
        ge=0,
        le=1,
        title="Containment threshold",
        json_schema_extra=field_ui(
            group=_OVERLAP,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("resolve_overlaps")),
        ),
    )

    join_baselines: bool = Field(
        default=True,
        title="Join baselines",
        json_schema_extra=field_ui(
            group=_BASELINE, widget="switch", visible_when=_IS_CUSTOM
        ),
    )
    max_gap_heights: float = Field(
        default=1.2,
        ge=0,
        le=8,
        title="Maximum join gap",
        json_schema_extra=field_ui(
            group=_BASELINE,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    max_baseline_offset: float = Field(
        default=0.35,
        ge=0,
        le=2,
        title="Maximum baseline offset",
        json_schema_extra=field_ui(
            group=_BASELINE,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    max_angle_degrees: float = Field(
        default=15.0,
        ge=0,
        le=45,
        title="Maximum angle difference",
        json_schema_extra=field_ui(
            group=_BASELINE,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )

    drop_small_noise: bool = Field(
        default=True,
        title="Drop small noise",
        json_schema_extra=field_ui(
            group=_NOISE, widget="switch", visible_when=_IS_CUSTOM
        ),
    )
    min_height_ratio: float = Field(
        default=0.55,
        ge=0,
        le=2,
        title="Minimum height ratio",
        json_schema_extra=field_ui(
            group=_NOISE,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_small_noise")),
        ),
    )
    drop_elongated_small: bool = Field(
        default=False,
        title="Drop thin tree rows",
        json_schema_extra=field_ui(
            group=_NOISE,
            widget="switch",
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_small_noise")),
        ),
    )

    # Collapsed Advanced drawer (no group so the UI keeps them under > Advanced).
    pad_along_px: float = Field(
        default=0.0,
        ge=0,
        le=100,
        title="Pad along reading axis (px)",
        json_schema_extra=field_ui(advanced=True),
    )
    pad_across_px: float = Field(
        default=0.0,
        ge=0,
        le=100,
        title="Pad across reading axis (px)",
        json_schema_extra=field_ui(advanced=True),
    )
    simplify_tolerance_px: float = Field(
        default=1.5,
        ge=0,
        le=50,
        title="Simplify tolerance (px)",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_field_eq("polygon_shape", "simplified"),
        ),
    )
    merge_text_separator: str = Field(
        default=" ",
        max_length=16,
        title="Merged text separator",
        json_schema_extra=field_ui(advanced=True),
    )
    max_height_px: float = Field(
        default=0.0,
        ge=0,
        le=10000,
        title="Maximum height (px)",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_large_outliers")),
        ),
    )
    max_area_px: float = Field(
        default=0.0,
        ge=0,
        le=100_000_000,
        title="Maximum area (px)",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_large_outliers")),
        ),
    )
    micro_speck_area_px: float = Field(
        default=16.0,
        ge=0,
        le=10000,
        title="Micro-speck area (px)",
        json_schema_extra=field_ui(advanced=True, visible_when=_IS_CUSTOM),
    )
    partial_containment_merge_threshold: float = Field(
        default=0.45,
        ge=0,
        le=1,
        title="Partial containment threshold",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("resolve_overlaps")),
        ),
    )
    overlap_max_angle_degrees: float = Field(
        default=25.0,
        ge=0,
        le=90,
        title="Maximum overlap angle",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("resolve_overlaps")),
        ),
    )
    overlap_max_height_growth: float = Field(
        default=1.45,
        ge=1,
        le=5,
        title="Maximum overlap height growth",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("resolve_overlaps")),
        ),
    )
    min_neighbour_height_ratio: float = Field(
        default=0.55,
        ge=0.1,
        le=1,
        title="Minimum neighbour height ratio",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    max_merged_height_ratio: float = Field(
        default=1.45,
        ge=1,
        le=5,
        title="Maximum merged height ratio",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    square_aspect_threshold: float = Field(
        default=1.5,
        ge=1,
        le=5,
        title="Square aspect threshold",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    allow_short_fragment_joining: bool = Field(
        default=True,
        title="Join short fragments",
        json_schema_extra=field_ui(
            widget="switch",
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    max_chain_members: int = Field(
        default=8,
        ge=2,
        le=64,
        title="Maximum chain members",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("join_baselines")),
        ),
    )
    noise_square_aspect: float = Field(
        default=2.0,
        ge=1,
        le=10,
        title="Noise square aspect",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_small_noise")),
        ),
    )
    min_width_px: float = Field(
        default=0.0,
        ge=0,
        le=10000,
        title="Minimum width (px)",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_small_noise")),
        ),
    )
    min_height_px: float = Field(
        default=0.0,
        ge=0,
        le=10000,
        title="Minimum height (px)",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_small_noise")),
        ),
    )
    min_area_px: float = Field(
        default=0.0,
        ge=0,
        le=10_000_000,
        title="Minimum area (px)",
        json_schema_extra=field_ui(
            advanced=True,
            visible_when=when_all(_IS_CUSTOM, when_field_truthy("drop_small_noise")),
        ),
    )

    def to_options(self) -> PostprocessOptions:
        if self.preset != "custom":
            return preset_options(
                self.preset,
                polygon_shape=self.polygon_shape,
                pad_along_px=self.pad_along_px,
                pad_across_px=self.pad_across_px,
                simplify_tolerance_px=self.simplify_tolerance_px,
                merge_text_separator=self.merge_text_separator,
            )
        return PostprocessOptions(
            min_score=self.min_score,
            drop_large_outliers=self.drop_large_outliers,
            max_height_ratio=self.max_height_ratio,
            max_height_px=self.max_height_px,
            max_area_px=self.max_area_px,
            micro_speck_area_px=self.micro_speck_area_px,
            resolve_overlaps=self.resolve_overlaps,
            overlap_mode=self.overlap_mode,
            merge_iou_threshold=self.merge_iou_threshold,
            containment_threshold=self.containment_threshold,
            partial_containment_merge_threshold=(
                self.partial_containment_merge_threshold
            ),
            overlap_max_angle_degrees=self.overlap_max_angle_degrees,
            overlap_max_height_growth=self.overlap_max_height_growth,
            join_baselines=self.join_baselines,
            max_gap_heights=self.max_gap_heights,
            max_baseline_offset=self.max_baseline_offset,
            max_angle_degrees=self.max_angle_degrees,
            min_neighbour_height_ratio=self.min_neighbour_height_ratio,
            max_merged_height_ratio=self.max_merged_height_ratio,
            square_aspect_threshold=self.square_aspect_threshold,
            allow_short_fragment_joining=self.allow_short_fragment_joining,
            max_chain_members=self.max_chain_members,
            drop_small_noise=self.drop_small_noise,
            min_height_ratio=self.min_height_ratio,
            drop_elongated_small=self.drop_elongated_small,
            noise_square_aspect=self.noise_square_aspect,
            min_width_px=self.min_width_px,
            min_height_px=self.min_height_px,
            min_area_px=self.min_area_px,
            polygon_shape=self.polygon_shape,
            pad_along_px=self.pad_along_px,
            pad_across_px=self.pad_across_px,
            simplify_tolerance_px=self.simplify_tolerance_px,
            merge_text_separator=self.merge_text_separator,
        )


_CONFIG_UI_ERRORS = validate_config_ui_schema(
    PostprocessRegionsConfig.model_json_schema(),
    input_ports={"regions"},
)
if _CONFIG_UI_ERRORS:
    _rendered = "; ".join(_CONFIG_UI_ERRORS)
    raise RuntimeError(f"PostprocessRegionsConfig UI schema is invalid: {_rendered}")


class PostprocessRegionsInput(NodeInput):
    regions: TiffTextRegions = Field(title="Text regions")


class PostprocessRegionsOutput(NodeOutput):
    regions: TiffTextRegions = Field(title="Text regions")
    dropped: TiffTextRegions = Field(title="Dropped regions")


@MAP_TOPONYMS.node(
    operator_id="ocr.postprocess_tiff_regions",
    version=1,
    title="Postprocess TIFF text regions",
    factory=lambda context: PostprocessTiffRegionsNode(context.open_tiff_page),
)
@final
class PostprocessTiffRegionsNode(
    Node[PostprocessRegionsConfig, PostprocessRegionsInput, PostprocessRegionsOutput]
):
    """Drops noise and outliers, resolves overlaps, and joins boxes on one baseline."""

    def __init__(self, open_page: TiffPageOpener | None = None) -> None:
        self._open_page = open_page

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: PostprocessRegionsConfig,
        inputs: PostprocessRegionsInput,
        /,
    ) -> PostprocessRegionsOutput:
        detected = inputs.regions
        max_x: float | None = None
        max_y: float | None = None
        if (
            detected.regions
            and self._open_page is not None
            and (
                config.pad_along_px > 0
                or config.pad_across_px > 0
                or config.polygon_shape in ("oriented_rect", "keep_original")
            )
        ):
            page = await self._open_page(
                context.workspace_id,
                detected.source.artifact_id,
                page=detected.window.page,
            )
            max_x = float(page.width)
            max_y = float(page.height)
        result = postprocess_regions(
            detected.regions, config.to_options(), max_x=max_x, max_y=max_y
        )
        context.output_metadata.update(result.stats.to_metadata())
        return PostprocessRegionsOutput(
            regions=TiffTextRegions(
                source=detected.source,
                window=detected.window,
                regions=result.regions,
            ),
            dropped=TiffTextRegions(
                source=detected.source,
                window=detected.window,
                regions=result.dropped,
            ),
        )

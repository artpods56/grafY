"""Run the TIFF text-region postprocessing stages in order."""

from collections.abc import Sequence

from grafy_core.contracts.ocr import TextRegion

from grafy_plugin_map_toponyms.region_postprocess.baseline import join_baselines
from grafy_plugin_map_toponyms.region_postprocess.filters import (
    filter_small_noise,
    prefilter_regions,
)
from grafy_plugin_map_toponyms.region_postprocess.geometry import (
    clamp_polygon,
    reading_order_key,
    shape_polygon,
)
from grafy_plugin_map_toponyms.region_postprocess.overlap import resolve_overlaps
from grafy_plugin_map_toponyms.region_postprocess.types import (
    PostprocessOptions,
    PostprocessResult,
    PostprocessStats,
)


def postprocess_regions(
    regions: Sequence[TextRegion],
    options: PostprocessOptions | None = None,
    *,
    max_x: float | None = None,
    max_y: float | None = None,
) -> PostprocessResult:
    """Filter, join, and reshape detected text regions."""
    opts = options or PostprocessOptions()
    pre = prefilter_regions(regions, opts)
    ov = resolve_overlaps(pre.kept, opts)
    joined = join_baselines(ov.kept, opts)
    noise = filter_small_noise(
        joined.boxes, letter_height=pre.letter_height, options=opts
    )

    output_regions: list[TextRegion] = []
    # Degenerate inputs never become boxes. Shaping can drop more.
    invalid_dropped = pre.invalid_dropped
    for box in noise.kept:
        polygon = shape_polygon(
            box,
            polygon_shape=opts.polygon_shape,
            pad_along_px=opts.pad_along_px,
            pad_across_px=opts.pad_across_px,
            simplify_tolerance_px=opts.simplify_tolerance_px,
            max_x=max_x,
            max_y=max_y,
        )
        if polygon is None:
            polygon = clamp_polygon(box.region.polygon, max_x=max_x, max_y=max_y)
        if polygon is None:
            invalid_dropped += 1
            continue
        output_regions.append(
            TextRegion(polygon=polygon, text=box.region.text, score=box.region.score)
        )

    output_regions.sort(key=reading_order_key)
    dropped = sorted(
        [*pre.dropped, *ov.dropped, *noise.dropped],
        key=reading_order_key,
    )
    return PostprocessResult(
        regions=output_regions,
        dropped=dropped,
        stats=PostprocessStats(
            input_regions=len(regions),
            invalid_dropped=invalid_dropped,
            score_dropped=pre.score_dropped,
            outliers_dropped=pre.outliers_dropped,
            micro_specks_dropped=pre.micro_specks_dropped,
            overlaps_resolved=ov.overlaps_resolved,
            spans_joined=joined.spans_joined,
            noise_dropped=noise.noise_dropped,
            output_regions=len(output_regions),
            estimated_letter_height=pre.letter_height,
        ),
    )

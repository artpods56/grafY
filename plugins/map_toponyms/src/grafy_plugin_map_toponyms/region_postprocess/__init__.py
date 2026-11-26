"""Modular postprocessing pipeline for detected TIFF text regions."""

from grafy_plugin_map_toponyms.region_postprocess.node import (
    PostprocessRegionsConfig,
    PostprocessRegionsInput,
    PostprocessRegionsOutput,
    PostprocessTiffRegionsNode,
)
from grafy_plugin_map_toponyms.region_postprocess.pipeline import postprocess_regions
from grafy_plugin_map_toponyms.region_postprocess.types import (
    OverlapMode,
    PolygonShape,
    PostprocessOptions,
    PostprocessPreset,
    PostprocessResult,
    PostprocessStats,
    RectCorners,
    RegionBox,
    preset_options,
)

__all__ = [
    "OverlapMode",
    "PolygonShape",
    "PostprocessOptions",
    "PostprocessPreset",
    "PostprocessRegionsConfig",
    "PostprocessRegionsInput",
    "PostprocessRegionsOutput",
    "PostprocessResult",
    "PostprocessStats",
    "PostprocessTiffRegionsNode",
    "RectCorners",
    "RegionBox",
    "postprocess_regions",
    "preset_options",
]

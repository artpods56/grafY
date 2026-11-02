"""Stored spatial compatibility across API readers and GIS producers."""

import json
from collections.abc import Callable
from typing import cast
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from grafy_api.v1.routes.artifacts.models import GeoMapLayerPayload
from grafy_core.spatial_contracts import (
    GeoFeatureCollectionPayload,
    GeoRasterProjectionMetadata,
    GeoVectorProjectionMetadata,
)
from grafy_plugin_gis.models import (
    GeoFeatureCollection,
    GeoMapLayer,
    RasterProjectionMetadata,
    VectorProjectionMetadata,
)


def test_feature_reader_preserves_legacy_payload_while_producer_checks_geometry() -> (
    None
):
    payload = {
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}}
        ],
        "source_name": "legacy",
        "bounds": None,
    }

    assert GeoFeatureCollectionPayload.model_validate(payload).bounds is None
    with pytest.raises(ValidationError, match="bounds do not match"):
        GeoFeatureCollection.model_validate(payload)


def test_feature_producer_serialization_matches_stored_contract() -> None:
    producer = GeoFeatureCollection.from_features(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 2]},
                "properties": {"name": "Żółw"},
            }
        ],
        "sample",
    )
    reader = GeoFeatureCollectionPayload.model_validate_json(producer.model_dump_json())

    assert reader.model_dump_json() == producer.model_dump_json()
    assert reader.bounds == (1.0, 2.0, 1.0, 2.0)


def test_vector_producer_defaults_do_not_make_stored_fields_optional() -> None:
    producer = VectorProjectionMetadata(
        bucket="artifacts",
        object_key="map.pmtiles",
        byte_size=1,
        sha256="a" * 64,
        min_zoom=0,
        max_zoom=10,
        source_layer="features",
        bounds=None,
        compiler="fixture",
    )
    payload = producer.model_dump(mode="json")
    assert (
        GeoVectorProjectionMetadata.model_validate(payload).model_dump()
        == producer.model_dump()
    )
    del payload["kind"]
    del payload["content_type"]

    assert VectorProjectionMetadata.model_validate(payload).kind == "pmtiles"
    with pytest.raises(ValidationError) as error:
        GeoVectorProjectionMetadata.model_validate(payload)
    assert {tuple(item["loc"]) for item in error.value.errors()} == {
        ("kind",),
        ("content_type",),
    }


def test_raster_reader_preserves_bounds_while_producer_validates_them() -> None:
    producer = RasterProjectionMetadata(
        bucket="artifacts",
        prefix="tiles",
        min_zoom=0,
        max_zoom=10,
        bounds=(0, 0, 1, 1),
        source_crs="EPSG:4326",
        width=256,
        height=256,
        band_count=3,
        compiler="fixture",
    )
    payload = producer.model_dump(mode="json")
    assert (
        GeoRasterProjectionMetadata.model_validate(payload).model_dump()
        == producer.model_dump()
    )
    payload["bounds"] = [200, 0, 201, 1]

    assert GeoRasterProjectionMetadata.model_validate(payload).bounds == (
        200,
        0,
        201,
        1,
    )
    with pytest.raises(ValidationError, match="longitudes must be within"):
        RasterProjectionMetadata.model_validate(payload)


@pytest.mark.parametrize("producer", [False, True])
def test_vector_zoom_range_is_rejected_by_reader_and_producer(producer: bool) -> None:
    model = VectorProjectionMetadata if producer else GeoVectorProjectionMetadata
    with pytest.raises(ValidationError, match="min_zoom must not exceed max_zoom"):
        model(
            kind="pmtiles",
            bucket="artifacts",
            object_key="map.pmtiles",
            content_type="application/vnd.pmtiles",
            byte_size=1,
            sha256="a" * 64,
            min_zoom=10,
            max_zoom=0,
            source_layer="features",
            bounds=None,
            compiler="fixture",
        )


_POINT_STYLE: dict[str, object] = {
    "enabled": True,
    "color": "#dc2626",
    "opacity": 1.0,
    "radius": 5.0,
    "stroke_color": "#ffffff",
    "stroke_width": 1.0,
}
_VECTOR_STYLE: dict[str, object] = {
    "kind": "vector",
    "fill": {"enabled": True, "color": "#2563eb", "opacity": 0.45},
    "line": {"enabled": True, "color": "#1d4ed8", "opacity": 1.0, "width": 1.5},
    "outline": {"enabled": True, "color": "#1d4ed8", "opacity": 1.0, "width": 1.5},
    "point": _POINT_STYLE,
    "label": None,
}
_RASTER_STYLE: dict[str, object] = {
    "kind": "raster",
    "opacity": 1.0,
    "brightness_min": 0.0,
    "brightness_max": 1.0,
    "contrast": 0.0,
    "saturation": 0.0,
    "hue": 0.0,
    "resampling": "linear",
}


def _category(category_id: str, values: list[object], *, min_zoom: int = 0) -> dict[str, object]:
    return {
        "id": category_id,
        "title": f"Category {category_id}",
        "values": values,
        "point": _POINT_STYLE,
        "min_zoom": min_zoom,
        "max_zoom": 22,
    }


def _categorized(*categories: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "categorized_points",
        "category_property": "type",
        "categories": list(categories),
        "label": None,
    }


def _stored_layer(
    *,
    source: str = "geo.feature_collection",
    style: dict[str, object] | None = None,
    min_zoom: int = 0,
    max_zoom: int = 22,
) -> dict[str, object]:
    """One layer as its producer stores it, so both readers see the same document."""

    layer = GeoMapLayer.model_validate(
        {
            "title": "Layer",
            "source": {
                "kind": (
                    "feature_collection" if "feature" in source else "raster_scan"
                ),
                "artifact": {
                    "artifact_id": str(UUID(int=7)),
                    "artifact_type": source,
                    "schema_version": 1,
                    "content_hash": None,
                },
            },
            "style": _VECTOR_STYLE if style is None else style,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
        }
    )
    return cast(dict[str, object], json.loads(layer.model_dump_json()))


_REJECTED = [
    (
        "inverted layer zoom range",
        lambda: _stored_layer(min_zoom=12, max_zoom=4),
        "min_zoom must not exceed max_zoom",
    ),
    (
        "feature source with a raster style",
        lambda: _stored_layer(style=_RASTER_STYLE),
        "Feature collection sources require vector style",
    ),
    (
        "raster source with a vector style",
        lambda: _stored_layer(source="geo.raster_scan"),
        "Raster scan and WMS sources require raster style",
    ),
    (
        "repeated category id",
        lambda: _stored_layer(
            style=_categorized(_category("cities", [1]), _category("cities", [2])),
        ),
        "category ids must be unique",
    ),
    (
        "one value in two categories",
        lambda: _stored_layer(
            style=_categorized(_category("cities", [1, 2]), _category("villages", [2])),
        ),
        "category values must not appear in multiple categories",
    ),
    (
        "repeated value inside one category",
        lambda: _stored_layer(style=_categorized(_category("cities", [4, 4]))),
        "category values must be unique",
    ),
    (
        "category zoom outside the layer zoom range",
        lambda: _stored_layer(
            style=_categorized(_category("cities", [1], min_zoom=18)),
            min_zoom=0,
            max_zoom=10,
        ),
        "zoom range does not overlap",
    ),
]

_LAYER_MODELS = pytest.mark.parametrize(
    "model",
    [GeoMapLayer, GeoMapLayerPayload],
    ids=["producer", "reader"],
)


@_LAYER_MODELS
@pytest.mark.parametrize(
    ("label", "build", "message"),
    _REJECTED,
    ids=[label for label, _build, _message in _REJECTED],
)
def test_layer_rules_reject_the_same_payload_on_both_sides(
    model: type[BaseModel],
    label: str,
    build: Callable[[], dict[str, object]],
    message: str,
) -> None:
    del label
    with pytest.raises(ValidationError, match=message):
        model.model_validate(build())


@_LAYER_MODELS
def test_category_values_keep_their_python_type_on_both_sides(
    model: type[BaseModel],
) -> None:
    """`1`, `1.0` and `True` are three category values, not one written three ways."""

    payload = _stored_layer(
        style=_categorized(_category("kinds", [1, 1.0, True]), _category("years", [2])),
    )

    assert isinstance(model.model_validate(payload), model)

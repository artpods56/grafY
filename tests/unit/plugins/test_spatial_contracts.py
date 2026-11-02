"""Stored spatial compatibility across API readers and GIS producers."""

import pytest
from pydantic import ValidationError

from grafy_core.spatial_contracts import (
    GeoFeatureCollectionPayload,
    GeoRasterProjectionMetadata,
    GeoVectorProjectionMetadata,
)
from grafy_plugin_gis.models import (
    GeoFeatureCollection,
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

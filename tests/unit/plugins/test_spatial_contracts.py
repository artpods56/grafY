"""Stored spatial compatibility across API readers and GIS producers."""

import pytest
from pydantic import ValidationError

from grafy_core.spatial_contracts import (
    GeoFeatureCollection,
    GeoFeatureCollectionPayload,
)


def test_feature_reader_accepts_an_unbounded_payload_while_producer_checks_geometry() -> (
    None
):
    payload = {
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}}
        ],
        "source_name": "unbounded",
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

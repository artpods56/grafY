"""API and GIS reads agree on logical bytes and preserve validation boundaries."""

from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.v1.routes.artifacts.services import (
    ArtifactService,
    ArtifactContentUnavailableError,
)
from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    JsonCollection,
    save_json_collections,
)
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, JsonObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.resolvers import ResolutionError
from grafy_plugin_gis.persistence import FeatureCollectionResolver
from grafy_storage import LocalFileObjectStore


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["api", "gis"])
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "legacy_no_integrity",
        "wrong_size",
        "wrong_hash",
        "wrong_collection",
        "incomplete",
        "missing_kind",
        "invalid_bounds",
    ],
)
async def test_complete_feature_reads_preserve_integrity_and_reader_validation(
    tmp_path: Path,
    reader: Literal["api", "gis"],
    case: str,
) -> None:
    storage = LocalFileObjectStore(tmp_path)
    uow = InMemoryUnitOfWork()
    workspace_id = uuid4()
    features: list[JsonObject] = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "properties": {"name": "Żółw"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [3, 4]},
            "properties": {},
        },
    ]
    bounds = None if case == "invalid_bounds" else [1.0, 2.0, 3.0, 4.0]
    metadata: JsonObject = {
        "kind": "geo.feature_collection",
        "crs": "EPSG:4326",
        "source_name": "sample",
        "bounds": bounds,
    }
    if case == "missing_kind":
        del metadata["kind"]
    stored = await save_json_collections(
        storage,
        bucket="artifacts",
        artifact_type=ArtifactTypeKey("geo.feature_collection", 1),
        collections=[
            JsonCollection(
                id="wrong" if case == "wrong_collection" else "features", items=features
            )
        ],
        metadata=metadata,
        node_id="source",
        workspace_id=workspace_id,
    )
    expected = json.dumps(
        {
            "type": "FeatureCollection",
            "crs": "EPSG:4326",
            "features": features,
            "source_name": "sample",
            "bounds": bounds,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    artifact = ArtifactObject(
        workspace_id=workspace_id,
        artifact_type="geo.feature_collection",
        schema_version=1,
        content_type="application/geo+json",
        bucket=stored.bucket,
        object_key=stored.manifest_path,
        byte_size=None
        if case == "legacy_no_integrity"
        else len(expected) + (1 if case == "wrong_size" else 0),
        sha256=None
        if case == "legacy_no_integrity"
        else ("f" * 64 if case == "wrong_hash" else sha256(expected).hexdigest()),
        metadata={
            "storage_format": JSON_COLLECTIONS_STORAGE_FORMAT,
            "feature_count": 1 if case == "incomplete" else 2,
            "manifest_byte_size": stored.manifest_byte_size,
            "manifest_sha256": stored.manifest_sha256,
        },
    )
    async with uow as transaction:
        await transaction.artifacts.add(artifact)
        await transaction.commit()
    error_fragment = {
        "wrong_size": "contains",
        "wrong_hash": "SHA-256",
        "wrong_collection": "one 'features' collection",
        "incomplete": "page is incomplete",
    }.get(case)
    if case == "missing_kind" and reader == "api":
        error_fragment = "kind"
    if case == "invalid_bounds" and reader == "gis":
        error_fragment = "bounds do not match"
    service: ArtifactService | None = None
    if reader == "api":
        service = ArtifactService(
            uow, storage, availability=ArtifactAvailability(uow, storage)
        )
        operation = service.load_content(artifact)
        error_type = ArtifactContentUnavailableError
    else:
        operation = FeatureCollectionResolver(uow=uow, storage=storage).resolve(
            artifact.ref(), workspace_id
        )
        error_type = ResolutionError
    try:
        if error_fragment is not None:
            with pytest.raises(error_type) as error:
                await operation
            assert str(artifact.id) in str(error.value)
            assert error.value.__cause__ is not None
            assert error_fragment in str(error.value.__cause__)
        else:
            result = await operation
            if isinstance(result, bytes):
                assert result == expected
            else:
                assert result.model_dump(mode="json") == json.loads(expected)
    finally:
        if service is not None:
            await service.close()

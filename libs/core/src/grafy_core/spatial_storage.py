"""Read complete stored feature collections and verify their logical bytes."""

from dataclasses import dataclass
from hashlib import sha256

from grafy_core.artifact_collections import load_json_collections_page
from grafy_core.artifacts import ArtifactObject
from grafy_core.ports.storage import FileStoragePort
from grafy_core.spatial_contracts import (
    GeoFeatureCollectionMetadata,
    GeoFeatureCollectionPayload,
)


@dataclass(frozen=True, slots=True)
class LoadedFeatureCollection[Payload: GeoFeatureCollectionPayload]:
    payload: Payload
    content: bytes


async def load_feature_collection[Payload: GeoFeatureCollectionPayload](
    artifact: ArtifactObject,
    storage: FileStoragePort,
    *,
    feature_count: int,
    metadata_type: type[GeoFeatureCollectionMetadata],
    payload_type: type[Payload],
) -> LoadedFeatureCollection[Payload]:
    page = await load_json_collections_page(
        artifact,
        storage,
        offset=0,
        limit=max(1, feature_count),
    )
    metadata = metadata_type.model_validate(page.metadata)
    if len(page.collections) != 1 or page.collections[0].id != "features":
        raise ValueError(
            "Geo feature collection manifest must contain one 'features' collection"
        )
    collection = page.collections[0]
    if len(collection.items) != collection.total_items:
        raise ValueError("Geo feature collection page is incomplete")
    payload = payload_type(
        features=collection.items,
        source_name=metadata.source_name,
        bounds=metadata.bounds,
    )
    content = payload.canonical_json_bytes()
    verify_spatial_artifact_content(artifact, content)
    return LoadedFeatureCollection(payload=payload, content=content)


def verify_spatial_artifact_content(artifact: ArtifactObject, content: bytes) -> None:
    if artifact.byte_size is not None and len(content) != artifact.byte_size:
        raise ValueError(
            f"Spatial artifact {artifact.id} contains {len(content)} bytes, "
            f"expected {artifact.byte_size}"
        )
    if artifact.sha256 is not None:
        observed_sha256 = sha256(content).hexdigest()
        if observed_sha256 != artifact.sha256:
            raise ValueError(
                f"Spatial artifact {artifact.id} has SHA-256 "
                f"{observed_sha256}, expected {artifact.sha256}"
            )

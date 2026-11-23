from hashlib import sha256
from typing import cast

from pydantic import BaseModel

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    SUPPORTED_JSON_COLLECTIONS_STORAGE_FORMATS,
    JsonCollection,
    JsonCollectionsManifest,
    save_json_collections,
)
from grafy_core.artifacts import JsonObject
from grafy_core.ports.storage import StoredFile
from grafy_core.runtime.artifact_values import (
    Artifact,
    ArtifactFiles,
    EncodedArtifact,
    StoredArtifact,
)
from grafy_core.runtime.portable_metadata import (
    PORTABLE_BUNDLE_METADATA_KEY,
    PortableArtifactBundleMetadata,
    PortableArtifactFile,
)
from grafy_core.runtime.resolvers import ArtifactContractError, ResolutionError
from grafy_core.spatial_contracts import (
    GeoFeatureCollection,
    GeoFeaturePropertyMetadata,
    GeoPropertyValueType,
    GeoStoredFeatureCollectionMetadata,
)
from grafy_core.spatial_storage import load_feature_collection
from grafy_plugin_gis.artifacts import GEO_FEATURE_COLLECTION


def _feature_property_fields(
    features: list[JsonObject],
) -> list[GeoFeaturePropertyMetadata]:
    observed: dict[str, set[GeoPropertyValueType]] = {}
    for feature in features:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        typed_properties = cast(dict[str, object], properties)
        for field_name, value in typed_properties.items():
            if not field_name or len(field_name) > 255:
                continue
            if value is None:
                value_type: GeoPropertyValueType = "null"
            elif isinstance(value, bool):
                value_type = "boolean"
            elif isinstance(value, int):
                value_type = "integer"
            elif isinstance(value, float):
                value_type = "number"
            elif isinstance(value, str):
                value_type = "text"
            else:
                value_type = "unknown"
            observed.setdefault(field_name, set()).add(value_type)
    return [
        GeoFeaturePropertyMetadata(
            id=field_name,
            title=field_name,
            value_type=(next(iter(value_types)) if len(value_types) == 1 else "mixed"),
        )
        for field_name, value_types in observed.items()
    ]


def _json_metadata(model: BaseModel) -> JsonObject:
    return cast(JsonObject, model.model_dump(mode="json"))


def feature_collection_artifact() -> Artifact[GeoFeatureCollection]:
    async def resolve(stored: StoredArtifact) -> GeoFeatureCollection:
        artifact = stored.row
        if artifact.bucket is None or artifact.object_key is None:
            raise ArtifactContractError(
                f"Feature collection artifact {artifact.id} has no storage object"
            )
        try:
            if (
                artifact.metadata.get("storage_format")
                not in SUPPORTED_JSON_COLLECTIONS_STORAGE_FORMATS
            ):
                raise ValueError(
                    f"Feature collection artifact {artifact.id} uses unsupported "
                    f"storage format {artifact.metadata.get('storage_format')!r}"
                )
            feature_count = artifact.metadata.get("feature_count")
            if (
                not isinstance(feature_count, int)
                or isinstance(feature_count, bool)
                or feature_count < 0
            ):
                raise ValueError(
                    f"Feature collection artifact {artifact.id} has invalid "
                    "feature_count metadata"
                )
            loaded = await load_feature_collection(
                artifact,
                stored.storage,
                feature_count=feature_count,
                metadata_type=GeoStoredFeatureCollectionMetadata,
                payload_type=GeoFeatureCollection,
            )
            return loaded.payload
        except (ArtifactContractError, ResolutionError):
            raise
        except Exception as exc:
            raise ResolutionError(
                f"Failed to resolve feature collection artifact {artifact.id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc

    async def write(
        value: GeoFeatureCollection,
        files: ArtifactFiles,
    ) -> EncodedArtifact:
        logical_content = value.canonical_json_bytes()
        content_hash = sha256(logical_content).hexdigest()
        property_fields = _feature_property_fields(value.features)
        manifest_metadata = GeoStoredFeatureCollectionMetadata(
            source_name=value.source_name,
            bounds=value.bounds,
            property_fields=property_fields,
        )
        stored = await save_json_collections(
            files.storage,
            bucket=files.bucket,
            artifact_type=GEO_FEATURE_COLLECTION.key,
            collections=[JsonCollection(id="features", items=value.features)],
            metadata=_json_metadata(manifest_metadata),
            node_id=files.node_id,
            workspace_id=files.workspace_id,
        )
        manifest_stream = await files.storage.load(
            stored.bucket,
            stored.manifest_path,
        )
        try:
            manifest_content = manifest_stream.read(stored.manifest_byte_size + 1)
        finally:
            manifest_stream.close()
        if (
            len(manifest_content) != stored.manifest_byte_size
            or sha256(manifest_content).hexdigest() != stored.manifest_sha256
        ):
            raise RuntimeError("Stored feature manifest identity changed")
        stored_manifest = JsonCollectionsManifest.model_validate_json(manifest_content)
        portable_files = [
            PortableArtifactFile(
                object_key=stored.manifest_path,
                byte_size=stored.manifest_byte_size,
                sha256=stored.manifest_sha256,
                content_type="application/json",
            ),
            *(
                PortableArtifactFile(
                    object_key=chunk.object_key,
                    byte_size=chunk.byte_size,
                    sha256=chunk.sha256,
                    content_type="application/json",
                )
                for collection in stored_manifest.collections
                for chunk in collection.chunks
            ),
        ]

        artifact_metadata: JsonObject = {
            "content_hash": content_hash,
            "storage_format": JSON_COLLECTIONS_STORAGE_FORMAT,
            "source_name": value.source_name,
            "crs": value.crs,
            "feature_count": stored.total_items,
            "property_fields": [_json_metadata(field) for field in property_fields],
            "logical_byte_size": len(logical_content),
            "storage_byte_size": stored.storage_byte_size,
            "manifest_byte_size": stored.manifest_byte_size,
            "manifest_sha256": stored.manifest_sha256,
        }
        if value.bounds is not None:
            artifact_metadata["bounds"] = list(value.bounds)
        artifact_metadata[PORTABLE_BUNDLE_METADATA_KEY] = (
            PortableArtifactBundleMetadata(
                files=tuple(portable_files),
            ).as_metadata_value()
        )
        return EncodedArtifact(
            content_type="application/geo+json",
            byte_size=len(logical_content),
            sha256=content_hash,
            stored=StoredFile(
                bucket=stored.bucket,
                path=stored.manifest_path,
                etag=None,
                version_id=None,
                byte_size=stored.manifest_byte_size,
                sha256=stored.manifest_sha256,
            ),
            metadata=artifact_metadata,
        )

    return Artifact(
        spec=GEO_FEATURE_COLLECTION,
        value_type=GeoFeatureCollection,
        resolve=resolve,
        write=write,
    )


__all__ = [
    "feature_collection_artifact",
]

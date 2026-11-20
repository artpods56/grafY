import json
import math
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
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
from grafy_core.bounded_subprocess import run_in_thread
from grafy_core.ports.storage import SaveFileCommand, StoredFile
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
    PortableMetadataReference,
)
from grafy_core.runtime.resolvers import ArtifactContractError, ResolutionError
from grafy_core.spatial_contracts import (
    GeoFeatureCollection,
    GeoFeaturePropertyMetadata,
    GeoPropertyValueType,
    GeoStoredFeatureCollectionMetadata,
    VectorProjectionMetadata,
)
from grafy_core.spatial_storage import (
    load_feature_collection,
    verify_spatial_artifact_content,
)
from grafy_plugin_gis.artifacts import GEO_FEATURE_COLLECTION, GEO_RASTER_SCAN
from grafy_plugin_gis.gdal import GdalCli, GdalError, RasterBounds
from grafy_plugin_gis.models import GeoRasterScan, RasterProjectionMetadata


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


def feature_collection_artifact(
    gdal: GdalCli | None = None,
) -> Artifact[GeoFeatureCollection]:
    compiler = gdal or GdalCli()

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

        vector_projection: VectorProjectionMetadata | None = None
        if value.bounds is not None:
            with TemporaryDirectory(prefix="grafy-gis-vector-") as directory:
                work_dir = Path(directory)
                source_path = work_dir / "features.geojson"
                projection_path = work_dir / "features.pmtiles"
                source_path.write_text(
                    json.dumps(
                        {
                            "type": "FeatureCollection",
                            "features": value.features,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                try:
                    compilation = await run_in_thread(
                        compiler.compile_geojson_to_pmtiles,
                        source_path,
                        projection_path,
                        source_layer="features",
                        min_zoom=0,
                        max_zoom=14,
                    )
                except GdalError as exc:
                    node_id = files.node_id or "<unknown>"
                    raise RuntimeError(
                        f"Failed to compile PMTiles for feature source "
                        f"{value.source_name!r} produced by node {node_id!r}"
                    ) from exc
                projection_content = projection_path.read_bytes()
                projection_hash = sha256(projection_content).hexdigest()
                projection_key = (
                    f"workspaces/{files.workspace_id}/"
                    f"{GEO_FEATURE_COLLECTION.key.id}/"
                    f"v{GEO_FEATURE_COLLECTION.key.schema_version}/"
                    f"projections/pmtiles/{projection_hash}.pmtiles"
                )
                try:
                    stored_projection = await files.storage.save(
                        SaveFileCommand(
                            bucket=files.bucket,
                            path=projection_key,
                            stream=BytesIO(projection_content),
                            content_type="application/vnd.pmtiles",
                            metadata={
                                "artifact_kind": GEO_FEATURE_COLLECTION.key.id,
                                "source": "gdal-pmtiles-projection",
                                "sha256": projection_hash,
                            },
                            allow_overwrite=True,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to persist PMTiles projection for feature source "
                        f"{value.source_name!r} at {files.bucket}/{projection_key}"
                    ) from exc
                vector_projection = VectorProjectionMetadata(
                    bucket=stored_projection.bucket,
                    object_key=stored_projection.path,
                    byte_size=stored_projection.byte_size,
                    sha256=stored_projection.sha256,
                    min_zoom=compilation.min_zoom,
                    max_zoom=compilation.max_zoom,
                    source_layer=compilation.source_layer,
                    bounds=value.bounds,
                    compiler=(f"{compilation.compiler} {compilation.compiler_version}"),
                )
                portable_files.append(
                    PortableArtifactFile(
                        object_key=stored_projection.path,
                        byte_size=stored_projection.byte_size,
                        sha256=stored_projection.sha256,
                        content_type="application/vnd.pmtiles",
                    )
                )

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
        if vector_projection is not None:
            artifact_metadata["vector_projection"] = _json_metadata(vector_projection)
            portable_references = (
                PortableMetadataReference(
                    path=("vector_projection", "bucket"),
                    kind="bucket",
                ),
                PortableMetadataReference(
                    path=("vector_projection", "object_key"),
                    kind="object",
                ),
            )
        else:
            portable_references = ()
        artifact_metadata[PORTABLE_BUNDLE_METADATA_KEY] = (
            PortableArtifactBundleMetadata(
                files=tuple(portable_files),
                references=portable_references,
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


def _mercator_y(latitude: float) -> float:
    clamped = max(-85.05112878, min(85.05112878, latitude))
    return math.asinh(math.tan(math.radians(clamped))) / math.tau


def _raster_zoom_range(
    bounds: RasterBounds, width: int, height: int
) -> tuple[int, int]:
    west, south, east, north = bounds
    span_x = (east - west) / 360
    span_y = _mercator_y(north) - _mercator_y(south)
    fit_zoom = -math.log2(max(span_x, span_y, 2.0**-22))
    native_zoom = -math.log2(max(256 * span_x / width, 256 * span_y / height, 2.0**-22))
    min_zoom = max(0, math.floor(fit_zoom) - 2)
    return min_zoom, max(min_zoom, min(22, math.ceil(native_zoom)))


def raster_scan_artifact(gdal: GdalCli | None = None) -> Artifact[GeoRasterScan]:
    compiler = gdal or GdalCli()

    async def resolve(stored: StoredArtifact) -> GeoRasterScan:
        artifact = stored.row
        if artifact.bucket is None or artifact.object_key is None:
            raise ArtifactContractError(
                f"Raster scan artifact {artifact.id} has no storage object"
            )
        source_name = artifact.metadata.get("source_name")
        original_filename = artifact.metadata.get("original_filename")
        if not isinstance(source_name, str) or not isinstance(original_filename, str):
            raise ArtifactContractError(
                f"Raster scan artifact {artifact.id} lacks source name or filename"
            )
        try:
            stream = await stored.storage.load(
                bucket=artifact.bucket,
                path=artifact.object_key,
            )
            try:
                content = stream.read()
            finally:
                stream.close()
            verify_spatial_artifact_content(artifact, content)
            return GeoRasterScan(
                content=content,
                filename=original_filename,
                source_name=source_name,
            )
        except (ArtifactContractError, ResolutionError):
            raise
        except Exception as exc:
            raise ResolutionError(
                f"Failed to resolve raster scan artifact {artifact.id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc

    async def write(value: GeoRasterScan, files: ArtifactFiles) -> EncodedArtifact:
        with TemporaryDirectory(prefix="grafy-gis-raster-") as directory:
            work_dir = Path(directory)
            source_path = work_dir / "source.tif"
            cog_path = work_dir / "source.cog.tif"
            source_path.write_bytes(value.content)
            try:
                cog = await run_in_thread(
                    compiler.normalize_geotiff_to_cog,
                    source_path,
                    cog_path,
                )
            except GdalError as exc:
                node_id = files.node_id or "<unknown>"
                raise RuntimeError(
                    f"Failed to validate and normalize GeoTIFF "
                    f"{value.filename!r} for raster source "
                    f"{value.source_name!r} produced by node {node_id!r}"
                ) from exc
            cog_content = cog_path.read_bytes()
            cog_hash = sha256(cog_content).hexdigest()
            if cog.bounds_wgs84 is None or cog.native_crs is None:
                raise RuntimeError(
                    f"GDAL could not derive complete georeferencing metadata "
                    f"for raster {value.source_name!r}"
                )
            min_zoom, max_zoom = _raster_zoom_range(
                cog.bounds_wgs84, cog.width, cog.height
            )

            cog_key = (
                f"workspaces/{files.workspace_id}/"
                f"{GEO_RASTER_SCAN.key.id}/v{GEO_RASTER_SCAN.key.schema_version}/"
                f"{cog_hash}.tif"
            )
            try:
                stored_cog = await files.storage.save(
                    SaveFileCommand(
                        bucket=files.bucket,
                        path=cog_key,
                        stream=BytesIO(cog_content),
                        content_type=(
                            "image/tiff; application=geotiff; profile=cloud-optimized"
                        ),
                        metadata={
                            "original_filename": value.filename,
                            "artifact_kind": GEO_RASTER_SCAN.key.id,
                            "source": "gdal-cog-normalization",
                            "sha256": cog_hash,
                        },
                        allow_overwrite=True,
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to persist canonical COG for raster "
                    f"{value.source_name!r} at {files.bucket}/{cog_key}"
                ) from exc

        raster_projection = RasterProjectionMetadata(
            bucket=stored_cog.bucket,
            prefix=None,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            bounds=cog.bounds_wgs84,
            source_crs=cog.native_crs,
            width=cog.width,
            height=cog.height,
            band_count=cog.bands,
            compiler=f"{cog.compiler} {cog.compiler_version}",
        )
        artifact_metadata: JsonObject = {
            "content_hash": stored_cog.sha256,
            "source_name": value.source_name,
            "original_filename": value.filename,
            "bounds": list(cog.bounds_wgs84),
            "source_crs": cog.native_crs,
            "raster_projection": _json_metadata(raster_projection),
        }
        artifact_metadata[PORTABLE_BUNDLE_METADATA_KEY] = (
            PortableArtifactBundleMetadata(
                files=(
                    PortableArtifactFile(
                        object_key=stored_cog.path,
                        byte_size=stored_cog.byte_size,
                        sha256=stored_cog.sha256,
                        content_type=(
                            "image/tiff; application=geotiff; profile=cloud-optimized"
                        ),
                    ),
                ),
                references=(
                    PortableMetadataReference(
                        path=("raster_projection", "bucket"),
                        kind="bucket",
                    ),
                ),
            ).as_metadata_value()
        )
        return EncodedArtifact(
            content_type="image/tiff; application=geotiff; profile=cloud-optimized",
            byte_size=stored_cog.byte_size,
            sha256=stored_cog.sha256,
            stored=stored_cog,
            metadata=artifact_metadata,
        )

    return Artifact(
        spec=GEO_RASTER_SCAN,
        value_type=GeoRasterScan,
        resolve=resolve,
        write=write,
    )


__all__ = [
    "feature_collection_artifact",
    "raster_scan_artifact",
]

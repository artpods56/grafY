import json
from asyncio import to_thread
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast, final, override
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    SUPPORTED_JSON_COLLECTIONS_STORAGE_FORMATS,
    JsonCollection,
    JsonCollectionsManifest,
    save_json_collections,
)
from grafy_core.spatial_contracts import GeoFeatureCollectionMetadata
from grafy_core.spatial_storage import (
    load_feature_collection,
    verify_spatial_artifact_content,
)
from grafy_core.artifacts import ArtifactObject, ArtifactRef, JsonObject
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.errors import NotFoundError
from grafy_core.ports.storage import (
    FileStoragePort,
    SaveFileCommand,
)
from grafy_core.runtime.persistence import ArtifactOutputWriter, ArtifactWriteContext
from grafy_core.runtime.object_set_bundle import (
    PORTABLE_BUNDLE_METADATA_KEY,
    PortableArtifactBundleMetadata,
    PortableArtifactFile,
    PortableMetadataReference,
)
from grafy_core.runtime.resolvers import (
    ArtifactContractError,
    ResolutionError,
    Resolver,
)

from grafy_plugin_gis.artifacts import GEO_FEATURE_COLLECTION, GEO_RASTER_SCAN
from grafy_plugin_gis.gdal import GdalCli, GdalError
from grafy_plugin_gis.models import (
    Bounds,
    GeoFeatureCollection,
    GeoRasterScan,
    RasterProjectionMetadata,
    VectorProjectionMetadata,
)

type _PropertyValueType = Literal[
    "text",
    "integer",
    "number",
    "boolean",
    "null",
    "mixed",
    "unknown",
]


class _FeaturePropertyFieldMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1, max_length=255)
    title: StrictStr = Field(min_length=1, max_length=1_024)
    value_type: _PropertyValueType


class _FeatureCollectionManifestMetadata(GeoFeatureCollectionMetadata):
    kind: Literal["geo.feature_collection"] = "geo.feature_collection"
    bounds: Bounds | None
    property_fields: list[_FeaturePropertyFieldMetadata] = Field(
        default_factory=list,
    )


def _feature_property_fields(
    features: list[JsonObject],
) -> list[_FeaturePropertyFieldMetadata]:
    observed: dict[str, set[_PropertyValueType]] = {}
    for feature in features:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        typed_properties = cast(dict[str, object], properties)
        for field_name, value in typed_properties.items():
            if not field_name or len(field_name) > 255:
                continue
            if value is None:
                value_type: _PropertyValueType = "null"
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
        _FeaturePropertyFieldMetadata(
            id=field_name,
            title=field_name,
            value_type=(next(iter(value_types)) if len(value_types) == 1 else "mixed"),
        )
        for field_name, value_types in observed.items()
    ]


def _json_metadata(model: BaseModel) -> JsonObject:
    return cast(JsonObject, model.model_dump(mode="json"))


def _provenance(context: ArtifactWriteContext) -> JsonObject:
    return {
        input_name: [
            {
                "artifact_id": str(ref.artifact_id),
                "artifact_type": ref.artifact_type,
                "schema_version": ref.schema_version,
            }
            for ref in refs
        ]
        for input_name, refs in context.provenance.refs_by_input.items()
    }


@final
class FeatureCollectionOutputWriter(ArtifactOutputWriter):
    artifact_type = GEO_FEATURE_COLLECTION.key

    def __init__(
        self,
        *,
        storage: FileStoragePort,
        uow: UnitOfWorkPort,
        bucket: str,
        storage_backend: str,
        gdal: GdalCli | None = None,
    ) -> None:
        self._storage = storage
        self._uow = uow
        self._bucket = bucket
        self._storage_backend = storage_backend
        self._gdal = gdal or GdalCli()

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        payload = GeoFeatureCollection.model_validate(value)
        logical_content = payload.canonical_json_bytes()
        content_hash = sha256(logical_content).hexdigest()
        property_fields = _feature_property_fields(payload.features)
        manifest_metadata = _FeatureCollectionManifestMetadata(
            source_name=payload.source_name,
            bounds=payload.bounds,
            property_fields=property_fields,
        )
        stored = await save_json_collections(
            self._storage,
            bucket=self._bucket,
            artifact_type=self.artifact_type,
            collections=[JsonCollection(id="features", items=payload.features)],
            metadata=_json_metadata(manifest_metadata),
            node_id=context.node_context.node_id,
            workspace_id=context.node_context.workspace_id,
        )
        manifest_stream = await self._storage.load(
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
        if payload.bounds is not None:
            with TemporaryDirectory(prefix="grafy-gis-vector-") as directory:
                work_dir = Path(directory)
                source_path = work_dir / "features.geojson"
                projection_path = work_dir / "features.pmtiles"
                source_path.write_text(
                    json.dumps(
                        {
                            "type": "FeatureCollection",
                            "features": payload.features,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                try:
                    compilation = await to_thread(
                        self._gdal.compile_geojson_to_pmtiles,
                        source_path,
                        projection_path,
                        source_layer="features",
                        min_zoom=0,
                        max_zoom=14,
                    )
                except GdalError as exc:
                    node_id = context.node_context.node_id or "<unknown>"
                    raise RuntimeError(
                        f"Failed to compile PMTiles for feature source "
                        f"{payload.source_name!r} produced by node {node_id!r}"
                    ) from exc
                projection_content = projection_path.read_bytes()
                projection_hash = sha256(projection_content).hexdigest()
                projection_key = (
                    f"workspaces/{context.node_context.workspace_id}/"
                    f"{self.artifact_type.id}/v{self.artifact_type.schema_version}/"
                    f"projections/pmtiles/{projection_hash}.pmtiles"
                )
                try:
                    stored_projection = await self._storage.save(
                        SaveFileCommand(
                            bucket=self._bucket,
                            path=projection_key,
                            stream=BytesIO(projection_content),
                            content_type="application/vnd.pmtiles",
                            metadata={
                                "artifact_kind": self.artifact_type.id,
                                "source": "gdal-pmtiles-projection",
                                "sha256": projection_hash,
                            },
                            allow_overwrite=True,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to persist PMTiles projection for feature source "
                        f"{payload.source_name!r} at {self._bucket}/{projection_key}"
                    ) from exc
                vector_projection = VectorProjectionMetadata(
                    bucket=stored_projection.bucket,
                    object_key=stored_projection.path,
                    byte_size=stored_projection.byte_size,
                    sha256=stored_projection.sha256,
                    min_zoom=compilation.min_zoom,
                    max_zoom=compilation.max_zoom,
                    source_layer=compilation.source_layer,
                    bounds=payload.bounds,
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

        artifact_metadata: JsonObject = dict(context.metadata)
        artifact_metadata.update(
            {
                "producer_node_id": context.node_context.node_id,
                "content_hash": content_hash,
                "storage_format": JSON_COLLECTIONS_STORAGE_FORMAT,
                "source_name": payload.source_name,
                "crs": payload.crs,
                "feature_count": stored.total_items,
                "property_fields": [_json_metadata(field) for field in property_fields],
                "logical_byte_size": len(logical_content),
                "storage_byte_size": stored.storage_byte_size,
                "manifest_byte_size": stored.manifest_byte_size,
                "manifest_sha256": stored.manifest_sha256,
            }
        )
        if payload.bounds is not None:
            artifact_metadata["bounds"] = list(payload.bounds)
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
        provenance = _provenance(context)
        if provenance:
            artifact_metadata["provenance"] = provenance
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/geo+json",
            storage_backend=self._storage_backend,
            bucket=stored.bucket,
            object_key=stored.manifest_path,
            byte_size=len(logical_content),
            sha256=content_hash,
            metadata=artifact_metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()


@final
class FeatureCollectionResolver(Resolver[GeoFeatureCollection]):
    source = GEO_FEATURE_COLLECTION.key
    target = cast(type[object], GeoFeatureCollection)

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
    ) -> None:
        self._uow = uow
        self._storage = storage

    @override
    async def resolve(
        self,
        ref: ArtifactRef,
        workspace_id: UUID,
    ) -> GeoFeatureCollection:
        if ref.key() != self.source:
            raise ArtifactContractError(
                f"Feature collection resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for {ref.artifact_id}"
            )
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            raise ArtifactContractError(
                f"Artifact repository returned a different artifact ref for "
                f"{ref.artifact_id}"
            )
        if artifact.bucket is None or artifact.object_key is None:
            raise ArtifactContractError(
                f"Feature collection artifact {ref.artifact_id} has no storage object"
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
                self._storage,
                feature_count=feature_count,
                metadata_type=_FeatureCollectionManifestMetadata,
                payload_type=GeoFeatureCollection,
            )
            return loaded.payload
        except (ArtifactContractError, ResolutionError):
            raise
        except Exception as exc:
            raise ResolutionError(
                f"Failed to resolve feature collection artifact {ref.artifact_id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc


@final
class RasterScanOutputWriter(ArtifactOutputWriter):
    artifact_type = GEO_RASTER_SCAN.key

    def __init__(
        self,
        *,
        storage: FileStoragePort,
        uow: UnitOfWorkPort,
        bucket: str,
        storage_backend: str,
        gdal: GdalCli | None = None,
    ) -> None:
        self._storage = storage
        self._uow = uow
        self._bucket = bucket
        self._storage_backend = storage_backend
        self._gdal = gdal or GdalCli()

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        payload = GeoRasterScan.model_validate(value)
        with TemporaryDirectory(prefix="grafy-gis-raster-") as directory:
            work_dir = Path(directory)
            source_path = work_dir / "source.tif"
            cog_path = work_dir / "source.cog.tif"
            tiles_dir = work_dir / "tiles"
            source_path.write_bytes(payload.content)
            try:
                cog = await to_thread(
                    self._gdal.normalize_geotiff_to_cog,
                    source_path,
                    cog_path,
                )
            except GdalError as exc:
                node_id = context.node_context.node_id or "<unknown>"
                raise RuntimeError(
                    f"Failed to validate and normalize GeoTIFF "
                    f"{payload.filename!r} for raster source "
                    f"{payload.source_name!r} produced by node {node_id!r}"
                ) from exc
            cog_content = cog_path.read_bytes()
            cog_hash = sha256(cog_content).hexdigest()
            try:
                tile_projection = await to_thread(
                    self._gdal.tile_raster_to_xyz,
                    cog_path,
                    tiles_dir,
                )
            except GdalError as exc:
                node_id = context.node_context.node_id or "<unknown>"
                raise RuntimeError(
                    f"Failed to compile XYZ tiles for raster source "
                    f"{payload.source_name!r} produced by node {node_id!r}"
                ) from exc
            tile_paths = sorted(tiles_dir.rglob("*.png"))
            if not tile_paths:
                raise RuntimeError(
                    f"GDAL produced no non-blank XYZ tiles for raster "
                    f"{payload.source_name!r}"
                )
            if (
                cog.bounds_wgs84 is None
                or cog.native_crs is None
                or tile_projection.min_zoom is None
                or tile_projection.max_zoom is None
            ):
                raise RuntimeError(
                    f"GDAL could not derive complete georeferencing and zoom "
                    f"metadata for raster {payload.source_name!r}"
                )
            if tile_projection.tile_count != len(tile_paths):
                raise RuntimeError(
                    f"GDAL reported {tile_projection.tile_count} XYZ tiles for raster "
                    f"{payload.source_name!r}, found {len(tile_paths)}"
                )

            cog_key = (
                f"workspaces/{context.node_context.workspace_id}/"
                f"{self.artifact_type.id}/v{self.artifact_type.schema_version}/"
                f"{cog_hash}.tif"
            )
            try:
                stored_cog = await self._storage.save(
                    SaveFileCommand(
                        bucket=self._bucket,
                        path=cog_key,
                        stream=BytesIO(cog_content),
                        content_type=(
                            "image/tiff; application=geotiff; profile=cloud-optimized"
                        ),
                        metadata={
                            "original_filename": payload.filename,
                            "artifact_kind": self.artifact_type.id,
                            "source": "gdal-cog-normalization",
                            "sha256": cog_hash,
                        },
                        allow_overwrite=True,
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to persist canonical COG for raster "
                    f"{payload.source_name!r} at {self._bucket}/{cog_key}"
                ) from exc

            tile_prefix = (
                f"workspaces/{context.node_context.workspace_id}/"
                f"{self.artifact_type.id}/v{self.artifact_type.schema_version}/"
                f"projections/{cog_hash}/xyz"
            )
            stored_tiles: list[PortableArtifactFile] = []
            for tile_path in tile_paths:
                relative_tile = tile_path.relative_to(tiles_dir).as_posix()
                tile_key = f"{tile_prefix}/{relative_tile}"
                tile_content = tile_path.read_bytes()
                tile_hash = sha256(tile_content).hexdigest()
                try:
                    stored_tile = await self._storage.save(
                        SaveFileCommand(
                            bucket=self._bucket,
                            path=tile_key,
                            stream=BytesIO(tile_content),
                            content_type="image/png",
                            metadata={
                                "artifact_kind": self.artifact_type.id,
                                "source": "gdal-xyz-projection",
                                "sha256": tile_hash,
                            },
                            allow_overwrite=True,
                        )
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to persist XYZ tile for raster "
                        f"{payload.source_name!r} at {self._bucket}/{tile_key}"
                    ) from exc
                stored_tiles.append(
                    PortableArtifactFile(
                        object_key=stored_tile.path,
                        byte_size=stored_tile.byte_size,
                        sha256=stored_tile.sha256,
                        content_type="image/png",
                    )
                )

        raster_projection = RasterProjectionMetadata(
            bucket=stored_cog.bucket,
            prefix=tile_prefix,
            min_zoom=tile_projection.min_zoom,
            max_zoom=tile_projection.max_zoom,
            bounds=cog.bounds_wgs84,
            source_crs=cog.native_crs,
            width=cog.width,
            height=cog.height,
            band_count=cog.bands,
            compiler=(f"{tile_projection.compiler} {tile_projection.compiler_version}"),
        )
        artifact_metadata: JsonObject = dict(context.metadata)
        artifact_metadata.update(
            {
                "producer_node_id": context.node_context.node_id,
                "content_hash": stored_cog.sha256,
                "source_name": payload.source_name,
                "original_filename": payload.filename,
                "bounds": list(cog.bounds_wgs84),
                "source_crs": cog.native_crs,
                "raster_projection": _json_metadata(raster_projection),
            }
        )
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
                    *stored_tiles,
                ),
                references=(
                    PortableMetadataReference(
                        path=("raster_projection", "bucket"),
                        kind="bucket",
                    ),
                    PortableMetadataReference(
                        path=("raster_projection", "prefix"),
                        kind="prefix",
                    ),
                ),
            ).as_metadata_value()
        )
        provenance = _provenance(context)
        if provenance:
            artifact_metadata["provenance"] = provenance
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type=("image/tiff; application=geotiff; profile=cloud-optimized"),
            storage_backend=self._storage_backend,
            bucket=stored_cog.bucket,
            object_key=stored_cog.path,
            byte_size=stored_cog.byte_size,
            sha256=stored_cog.sha256,
            metadata=artifact_metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()


@final
class RasterScanResolver(Resolver[GeoRasterScan]):
    source = GEO_RASTER_SCAN.key
    target = cast(type[object], GeoRasterScan)

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
    ) -> None:
        self._uow = uow
        self._storage = storage

    @override
    async def resolve(
        self,
        ref: ArtifactRef,
        workspace_id: UUID,
    ) -> GeoRasterScan:
        if ref.key() != self.source:
            raise ArtifactContractError(
                f"Raster scan resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for {ref.artifact_id}"
            )
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            raise ArtifactContractError(
                f"Artifact repository returned a different artifact ref for "
                f"{ref.artifact_id}"
            )
        if artifact.bucket is None or artifact.object_key is None:
            raise ArtifactContractError(
                f"Raster scan artifact {ref.artifact_id} has no storage object"
            )
        source_name = artifact.metadata.get("source_name")
        original_filename = artifact.metadata.get("original_filename")
        if not isinstance(source_name, str) or not isinstance(original_filename, str):
            raise ArtifactContractError(
                f"Raster scan artifact {ref.artifact_id} lacks source name or filename"
            )
        try:
            stream = await self._storage.load(
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
                f"Failed to resolve raster scan artifact {ref.artifact_id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc


__all__ = [
    "FeatureCollectionOutputWriter",
    "FeatureCollectionResolver",
    "RasterScanOutputWriter",
    "RasterScanResolver",
]

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from grafy_core.stored_models import load_stored_model
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, JsonObject
from grafy_core.ports.storage import (
    FileMetadata,
    FileStoragePort,
    SaveFileCommand,
)
from grafy_core.runtime.resolvers import (
    ArtifactContractError,
    ResolutionError,
)


JSON_COLLECTIONS_STORAGE_FORMAT = "grafy.json-collections.chunked.v1"
LEGACY_JSON_COLLECTIONS_STORAGE_FORMAT = "notarius.json-collections.chunked.v1"
SUPPORTED_JSON_COLLECTIONS_STORAGE_FORMATS = frozenset(
    {
        JSON_COLLECTIONS_STORAGE_FORMAT,
        LEGACY_JSON_COLLECTIONS_STORAGE_FORMAT,
    }
)
JSON_COLLECTION_CHUNK_ITEM_COUNT = 50
JSON_COLLECTION_CHUNK_TARGET_BYTE_SIZE = 512 * 1_024

_JSON_OBJECT_ADAPTER = TypeAdapter(JsonObject)


class JsonCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1)
    items: list[JsonObject]
    metadata: JsonObject = Field(default_factory=dict)


class JsonCollectionChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: StrictStr = Field(min_length=1)
    offset: StrictInt = Field(ge=0)
    items: list[JsonObject]


class JsonCollectionChunkDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: StrictInt = Field(ge=0)
    item_count: StrictInt = Field(ge=1)
    object_key: StrictStr = Field(min_length=1)
    byte_size: StrictInt = Field(ge=0)
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class JsonCollectionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1)
    item_count: StrictInt = Field(ge=0)
    chunks: list[JsonCollectionChunkDescriptor]
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_chunks_cover_items(self) -> Self:
        expected_offset = 0
        for chunk in self.chunks:
            if chunk.offset != expected_offset:
                raise ValueError(
                    f"Collection {self.id!r} chunk at offset {chunk.offset} "
                    f"must start at {expected_offset}"
                )
            expected_offset += chunk.item_count
        if expected_offset != self.item_count:
            raise ValueError(
                f"Collection {self.id!r} chunks cover {expected_offset} items, "
                f"expected {self.item_count}"
            )
        return self


class JsonCollectionsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal[
        "grafy.json-collections.chunked.v1",
        "notarius.json-collections.chunked.v1",
    ] = JSON_COLLECTIONS_STORAGE_FORMAT
    total_items: StrictInt = Field(ge=0)
    collections: list[JsonCollectionDescriptor]
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        collection_ids = [collection.id for collection in self.collections]
        if len(collection_ids) != len(set(collection_ids)):
            raise ValueError("JSON collection ids must be unique")
        observed_total = sum(collection.item_count for collection in self.collections)
        if observed_total != self.total_items:
            raise ValueError(
                f"JSON collections contain {observed_total} items, expected "
                f"{self.total_items}"
            )
        return self


class JsonCollectionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1)
    item_offset: StrictInt = Field(ge=0)
    total_items: StrictInt = Field(ge=0)
    items: list[JsonObject]
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_page_bounds(self) -> Self:
        if self.item_offset > self.total_items:
            raise ValueError("Collection page offset must not exceed total items")
        if self.item_offset + len(self.items) > self.total_items:
            raise ValueError("Collection page items exceed total items")
        return self


class JsonCollectionsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: list[JsonCollectionPage]
    offset: StrictInt = Field(ge=0)
    total_items: StrictInt = Field(ge=0)
    metadata: JsonObject = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredJsonCollections:
    bucket: str
    manifest_path: str
    manifest_byte_size: int
    manifest_sha256: str
    storage_byte_size: int
    total_items: int
    collection_count: int


async def save_json_collections(
    storage: FileStoragePort,
    *,
    bucket: str,
    artifact_type: ArtifactTypeKey,
    collections: list[JsonCollection],
    metadata: JsonObject,
    node_id: str | None,
    workspace_id: UUID,
) -> StoredJsonCollections:
    collection_ids = [collection.id for collection in collections]
    if len(collection_ids) != len(set(collection_ids)):
        raise ValueError("JSON collection ids must be unique")
    descriptors: list[JsonCollectionDescriptor] = []
    stored_byte_size = 0
    for collection in collections:
        chunks: list[JsonCollectionChunkDescriptor] = []
        offset = 0
        while offset < len(collection.items):
            chunk_end = offset
            estimated_byte_size = 64
            while (
                chunk_end < len(collection.items)
                and chunk_end - offset < JSON_COLLECTION_CHUNK_ITEM_COUNT
            ):
                item_byte_size = len(
                    _JSON_OBJECT_ADAPTER.dump_json(collection.items[chunk_end])
                )
                if (
                    chunk_end > offset
                    and estimated_byte_size + item_byte_size
                    > JSON_COLLECTION_CHUNK_TARGET_BYTE_SIZE
                ):
                    break
                estimated_byte_size += item_byte_size + 1
                chunk_end += 1
            chunk = JsonCollectionChunk(
                collection_id=collection.id,
                offset=offset,
                items=collection.items[offset:chunk_end],
            )
            content = chunk.model_dump_json().encode("utf-8")
            content_hash = sha256(content).hexdigest()
            storage_path = (
                f"workspaces/{workspace_id}/{artifact_type.id}/"
                f"v{artifact_type.schema_version}/chunks/"
                f"{content_hash}.json"
            )
            file_metadata: FileMetadata = {
                "artifact_kind": artifact_type.id,
                "sha256": content_hash,
            }
            if node_id is not None:
                file_metadata["job_id"] = node_id
            try:
                stored = await storage.save(
                    SaveFileCommand(
                        bucket=bucket,
                        path=storage_path,
                        stream=BytesIO(content),
                        content_type="application/json",
                        metadata=file_metadata,
                        allow_overwrite=True,
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to persist {artifact_type.id} collection "
                    f"{collection.id!r} items {offset} through "
                    f"{chunk_end - 1} for node {node_id!r} at "
                    f"{bucket}/{storage_path}"
                ) from exc
            stored_byte_size += stored.byte_size
            chunks.append(
                JsonCollectionChunkDescriptor(
                    offset=offset,
                    item_count=len(chunk.items),
                    object_key=stored.path,
                    byte_size=stored.byte_size,
                    sha256=stored.sha256,
                )
            )
            offset = chunk_end
        descriptors.append(
            JsonCollectionDescriptor(
                id=collection.id,
                item_count=len(collection.items),
                chunks=chunks,
                metadata=collection.metadata,
            )
        )

    manifest = JsonCollectionsManifest(
        total_items=sum(len(collection.items) for collection in collections),
        collections=descriptors,
        metadata=metadata,
    )
    manifest_content = manifest.model_dump_json().encode("utf-8")
    manifest_hash = sha256(manifest_content).hexdigest()
    manifest_path = (
        f"workspaces/{workspace_id}/{artifact_type.id}/"
        f"v{artifact_type.schema_version}/manifests/"
        f"{manifest_hash}.json"
    )
    try:
        stored_manifest = await storage.save(
            SaveFileCommand(
                bucket=bucket,
                path=manifest_path,
                stream=BytesIO(manifest_content),
                content_type="application/json",
                metadata={
                    "artifact_kind": artifact_type.id,
                    "sha256": manifest_hash,
                },
                allow_overwrite=True,
            )
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to persist {artifact_type.id} manifest for node "
            f"{node_id!r} at {bucket}/{manifest_path}"
        ) from exc
    return StoredJsonCollections(
        bucket=stored_manifest.bucket,
        manifest_path=stored_manifest.path,
        manifest_byte_size=stored_manifest.byte_size,
        manifest_sha256=stored_manifest.sha256,
        storage_byte_size=stored_byte_size + stored_manifest.byte_size,
        total_items=manifest.total_items,
        collection_count=len(manifest.collections),
    )


async def load_json_collections_manifest(
    artifact: ArtifactObject,
    storage: FileStoragePort,
) -> JsonCollectionsManifest:
    if artifact.bucket is None or artifact.object_key is None:
        raise ArtifactContractError(
            f"Artifact {artifact.id} does not have a JSON collections manifest"
        )
    manifest_byte_size = artifact.metadata.get("manifest_byte_size")
    if manifest_byte_size is not None and (
        not isinstance(manifest_byte_size, int)
        or isinstance(manifest_byte_size, bool)
        or manifest_byte_size < 0
    ):
        raise ArtifactContractError(
            f"Artifact {artifact.id} has invalid manifest_byte_size metadata"
        )
    manifest_sha256 = artifact.metadata.get("manifest_sha256")
    if manifest_sha256 is not None and (
        not isinstance(manifest_sha256, str)
        or len(manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in manifest_sha256)
    ):
        raise ArtifactContractError(
            f"Artifact {artifact.id} has invalid manifest_sha256 metadata"
        )
    try:
        return await load_stored_model(
            storage,
            bucket=artifact.bucket,
            object_key=artifact.object_key,
            model=JsonCollectionsManifest,
            expected_byte_size=manifest_byte_size,
            expected_sha256=manifest_sha256,
        )
    except Exception as exc:
        raise ResolutionError(
            f"Failed to load JSON collections manifest for artifact "
            f"{artifact.id} from {artifact.bucket}/{artifact.object_key}"
        ) from exc


async def load_json_collections_page(
    artifact: ArtifactObject,
    storage: FileStoragePort,
    *,
    offset: int,
    limit: int,
) -> JsonCollectionsPage:
    if offset < 0:
        raise ValueError("JSON collections page offset must not be negative")
    if limit < 1:
        raise ValueError("JSON collections page limit must be positive")
    if artifact.bucket is None:
        raise ArtifactContractError(
            f"Artifact {artifact.id} does not have a storage bucket"
        )
    manifest = await load_json_collections_manifest(artifact, storage)
    effective_offset = min(offset, manifest.total_items)
    page_end = min(offset + limit, manifest.total_items)
    collection_start = 0
    pages: list[JsonCollectionPage] = []
    for collection in manifest.collections:
        local_start = min(
            collection.item_count,
            max(0, effective_offset - collection_start),
        )
        local_end = min(
            collection.item_count,
            max(0, page_end - collection_start),
        )
        items: list[JsonObject] = []
        if local_start < local_end:
            for descriptor in collection.chunks:
                chunk_end = descriptor.offset + descriptor.item_count
                if chunk_end <= local_start or descriptor.offset >= local_end:
                    continue
                try:
                    chunk = await load_stored_model(
                        storage,
                        bucket=artifact.bucket,
                        object_key=descriptor.object_key,
                        model=JsonCollectionChunk,
                        expected_byte_size=descriptor.byte_size,
                        expected_sha256=descriptor.sha256,
                    )
                except Exception as exc:
                    raise ResolutionError(
                        f"Failed to load JSON collection {collection.id!r} "
                        f"chunk at offset {descriptor.offset} for artifact "
                        f"{artifact.id} from "
                        f"{artifact.bucket}/{descriptor.object_key}"
                    ) from exc
                if (
                    chunk.collection_id != collection.id
                    or chunk.offset != descriptor.offset
                    or len(chunk.items) != descriptor.item_count
                ):
                    raise ResolutionError(
                        f"JSON collection chunk {descriptor.object_key!r} does "
                        f"not match its manifest descriptor for artifact "
                        f"{artifact.id}"
                    )
                chunk_start = max(local_start, descriptor.offset)
                chunk_slice_end = min(local_end, chunk_end)
                items.extend(
                    chunk.items[
                        chunk_start - descriptor.offset : chunk_slice_end
                        - descriptor.offset
                    ]
                )
        pages.append(
            JsonCollectionPage(
                id=collection.id,
                item_offset=local_start,
                total_items=collection.item_count,
                items=items,
                metadata=collection.metadata,
            )
        )
        collection_start += collection.item_count
    return JsonCollectionsPage(
        collections=pages,
        offset=effective_offset,
        total_items=manifest.total_items,
        metadata=manifest.metadata,
    )


async def json_collections_artifact_is_accessible(
    artifact: ArtifactObject,
    storage: FileStoragePort,
) -> bool:
    if artifact.bucket is None or artifact.object_key is None:
        return False
    if await storage.stat(artifact.bucket, artifact.object_key) is None:
        return False
    try:
        manifest = await load_json_collections_manifest(artifact, storage)
    except ArtifactContractError:
        return False
    except ResolutionError as exc:
        if isinstance(exc.__cause__, ValueError):
            return False
        raise
    for collection in manifest.collections:
        for chunk in collection.chunks:
            if await storage.stat(artifact.bucket, chunk.object_key) is None:
                return False
    return True


async def json_collections_artifact_is_intact(
    artifact: ArtifactObject,
    storage: FileStoragePort,
) -> bool:
    if artifact.bucket is None or artifact.object_key is None:
        return False
    if await storage.stat(artifact.bucket, artifact.object_key) is None:
        return False
    try:
        manifest = await load_json_collections_manifest(artifact, storage)
    except ArtifactContractError:
        return False
    except ResolutionError as exc:
        if isinstance(exc.__cause__, ValueError):
            return False
        raise
    for collection in manifest.collections:
        for descriptor in collection.chunks:
            if await storage.stat(artifact.bucket, descriptor.object_key) is None:
                return False
            try:
                chunk = await load_stored_model(
                    storage,
                    bucket=artifact.bucket,
                    object_key=descriptor.object_key,
                    model=JsonCollectionChunk,
                    expected_byte_size=descriptor.byte_size,
                    expected_sha256=descriptor.sha256,
                )
            except (FileNotFoundError, ValueError):
                return False
            if (
                chunk.collection_id != collection.id
                or chunk.offset != descriptor.offset
                or len(chunk.items) != descriptor.item_count
            ):
                return False
    return True


__all__ = [
    "JSON_COLLECTIONS_STORAGE_FORMAT",
    "SUPPORTED_JSON_COLLECTIONS_STORAGE_FORMATS",
    "JSON_COLLECTION_CHUNK_ITEM_COUNT",
    "JSON_COLLECTION_CHUNK_TARGET_BYTE_SIZE",
    "JsonCollection",
    "JsonCollectionChunk",
    "JsonCollectionChunkDescriptor",
    "JsonCollectionDescriptor",
    "JsonCollectionPage",
    "JsonCollectionsManifest",
    "JsonCollectionsPage",
    "StoredJsonCollections",
    "json_collections_artifact_is_accessible",
    "json_collections_artifact_is_intact",
    "load_json_collections_manifest",
    "load_json_collections_page",
    "save_json_collections",
]

from uuid import UUID

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    json_collections_artifact_is_intact,
)
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.table_contracts import TABLE_DATA
from grafy_core.runtime.table_storage import table_artifact_is_accessible
from grafy_core.ports.materialized_outputs import WorkbenchUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.invocation_cache import InvocationCachePort


class InvocationCacheAccessError(RuntimeError):
    pass


class PersistentInvocationCache(InvocationCachePort):
    def __init__(
        self,
        *,
        unit_of_work: WorkbenchUnitOfWorkPort,
        storage: FileStoragePort,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._storage = storage

    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        async with self._unit_of_work as unit_of_work:
            entry = await unit_of_work.invocation_cache.get(
                workspace_id,
                key_sha256,
            )
            if entry is None:
                return None
            refs = _artifact_refs(entry.outputs)
            artifacts = await unit_of_work.artifacts.get_many(
                workspace_id, {ref.artifact_id for ref in refs}
            )

        stale = False
        for ref in refs:
            content_hash = ref.content_hash
            if (
                content_hash is None
                or len(content_hash) != 64
                or any(
                    character not in "0123456789abcdef" for character in content_hash
                )
            ):
                stale = True
                break
            artifact = artifacts.get(ref.artifact_id)
            if artifact is None or artifact.ref() != ref:
                stale = True
                break
            if (
                artifact.artifact_type == TABLE_DATA.key.id
                and artifact.schema_version == TABLE_DATA.key.schema_version
            ):
                try:
                    table_is_accessible = await table_artifact_is_accessible(
                        artifact,
                        self._storage,
                    )
                except Exception as exc:
                    raise InvocationCacheAccessError(
                        f"Failed to validate cached table artifact {artifact.id} "
                        f"for invocation {key_sha256}"
                    ) from exc
                if not table_is_accessible:
                    stale = True
                    break
                continue
            if (
                artifact.metadata.get("storage_format")
                == JSON_COLLECTIONS_STORAGE_FORMAT
            ):
                try:
                    collections_are_intact = await json_collections_artifact_is_intact(
                        artifact,
                        self._storage,
                    )
                except Exception as exc:
                    raise InvocationCacheAccessError(
                        f"Failed to validate cached chunked artifact "
                        f"{artifact.id} for invocation {key_sha256}"
                    ) from exc
                if not collections_are_intact:
                    stale = True
                    break
                continue
            if artifact.inline_payload is not None:
                continue
            if artifact.bucket is None or artifact.object_key is None:
                stale = True
                break
            try:
                object_exists = (
                    await self._storage.stat(
                        artifact.bucket,
                        artifact.object_key,
                    )
                    is not None
                )
            except Exception as exc:
                raise InvocationCacheAccessError(
                    f"Failed to validate cached artifact {artifact.id} for "
                    f"invocation {key_sha256}"
                ) from exc
            if not object_exists:
                stale = True
                break

        if stale:
            await self.remove_if_current(
                workspace_id,
                key_sha256,
                entry.generation,
            )
            return None
        return entry

    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        refs = _artifact_refs(entry.outputs)
        if any(
            ref.content_hash is None
            or len(ref.content_hash) != 64
            or any(
                character not in "0123456789abcdef" for character in ref.content_hash
            )
            for ref in refs
        ):
            return False
        async with self._unit_of_work as unit_of_work:
            inserted = await unit_of_work.invocation_cache.put_if_absent(entry)
            await unit_of_work.commit()
        return inserted

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        async with self._unit_of_work as unit_of_work:
            removed = await unit_of_work.invocation_cache.remove_if_current(
                workspace_id,
                key_sha256,
                generation,
            )
            await unit_of_work.commit()
        return removed


def _artifact_refs(
    outputs: dict[str, ArtifactOutputValue],
) -> tuple[ArtifactRef, ...]:
    refs: list[ArtifactRef] = []
    for value in outputs.values():
        if isinstance(value, ArtifactRefSequence):
            refs.extend(value.item_refs)
        else:
            refs.append(value)
    return tuple(refs)

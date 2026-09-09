import csv
import json
from collections.abc import AsyncIterator, Iterator
from hashlib import sha256
from io import StringIO

from pydantic import ValidationError

from grafy_core.stored_models import load_stored_model
from grafy_core.artifacts import ArtifactObject
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.resolvers import ArtifactContractError, ResolutionError
from grafy_core.table_contracts import (
    Table,
    TableChunk,
    TableManifest,
    TablePage,
    TableValue,
)


TABLE_CHUNK_ROW_COUNT = 100
TABLE_CHUNK_TARGET_BYTE_SIZE = 1_024 * 1_024
CSV_EXPORT_BUFFER_BYTES = 1_048_576


def iter_table_chunks(table: Table) -> Iterator[TableChunk]:
    """Yield deterministic bounded chunks for table storage and transport."""

    offset = 0
    while offset < len(table.rows):
        chunk_end = offset
        estimated_byte_size = 32
        while (
            chunk_end < len(table.rows) and chunk_end - offset < TABLE_CHUNK_ROW_COUNT
        ):
            row_byte_size = len(
                json.dumps(
                    table.rows[chunk_end],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if (
                chunk_end > offset
                and estimated_byte_size + row_byte_size > TABLE_CHUNK_TARGET_BYTE_SIZE
            ):
                break
            estimated_byte_size += row_byte_size + 1
            chunk_end += 1
        yield TableChunk(
            offset=offset,
            rows=table.rows[offset:chunk_end],
        )
        offset = chunk_end


async def load_table_manifest(
    artifact: ArtifactObject,
    storage: FileStoragePort,
) -> TableManifest:
    if artifact.bucket is None or artifact.object_key is None:
        raise ArtifactContractError(
            f"Table artifact {artifact.id} does not have a storage manifest"
        )
    manifest_byte_size = artifact.metadata.get("manifest_byte_size")
    if manifest_byte_size is not None and (
        not isinstance(manifest_byte_size, int)
        or isinstance(manifest_byte_size, bool)
        or manifest_byte_size < 0
    ):
        raise ArtifactContractError(
            f"Table artifact {artifact.id} has invalid manifest_byte_size metadata"
        )
    manifest_sha256 = artifact.metadata.get("manifest_sha256")
    if manifest_sha256 is not None and (
        not isinstance(manifest_sha256, str)
        or len(manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in manifest_sha256)
    ):
        raise ArtifactContractError(
            f"Table artifact {artifact.id} has invalid manifest_sha256 metadata"
        )
    try:
        return await load_stored_model(
            storage,
            bucket=artifact.bucket,
            object_key=artifact.object_key,
            model=TableManifest,
            expected_byte_size=manifest_byte_size,
            expected_sha256=manifest_sha256,
        )
    except Exception as exc:
        raise ResolutionError(
            f"Failed to load table manifest for artifact {artifact.id} from "
            f"{artifact.bucket}/{artifact.object_key}"
        ) from exc


async def _load_table_page_from_manifest(
    artifact: ArtifactObject,
    storage: FileStoragePort,
    *,
    manifest: TableManifest,
    offset: int,
    limit: int,
) -> TablePage:
    if artifact.bucket is None:
        raise ArtifactContractError(
            f"Table artifact {artifact.id} does not have a storage bucket"
        )
    page_end = min(offset + limit, manifest.row_count)
    rows: list[dict[str, TableValue]] = []
    for descriptor in manifest.chunks:
        chunk_end = descriptor.offset + descriptor.row_count
        if chunk_end <= offset or descriptor.offset >= page_end:
            continue
        try:
            chunk = await load_stored_model(
                storage,
                bucket=artifact.bucket,
                object_key=descriptor.object_key,
                model=TableChunk,
                expected_byte_size=descriptor.byte_size,
                expected_sha256=descriptor.sha256,
            )
        except Exception as exc:
            raise ResolutionError(
                f"Failed to load table chunk at offset {descriptor.offset} for "
                f"artifact {artifact.id} from "
                f"{artifact.bucket}/{descriptor.object_key}"
            ) from exc
        if chunk.offset != descriptor.offset or len(chunk.rows) != descriptor.row_count:
            raise ResolutionError(
                f"Table chunk {descriptor.object_key!r} does not match its manifest "
                f"descriptor for artifact {artifact.id}"
            )
        local_start = max(offset, descriptor.offset) - descriptor.offset
        local_end = min(page_end, chunk_end) - descriptor.offset
        rows.extend(chunk.rows[local_start:local_end])
    effective_offset = min(offset, manifest.row_count)
    return TablePage(
        columns=manifest.columns,
        rows=rows,
        offset=effective_offset,
        total_rows=manifest.row_count,
    )


async def load_table_page(
    artifact: ArtifactObject,
    storage: FileStoragePort,
    *,
    offset: int,
    limit: int,
) -> TablePage:
    if offset < 0:
        raise ValueError("Table page offset must not be negative")
    if limit < 1:
        raise ValueError("Table page limit must be positive")
    if artifact.inline_payload is not None:
        table = Table.model_validate(artifact.inline_payload)
        effective_offset = min(offset, len(table.rows))
        return TablePage(
            columns=table.columns,
            rows=table.rows[effective_offset : effective_offset + limit],
            offset=effective_offset,
            total_rows=len(table.rows),
        )

    manifest = await load_table_manifest(artifact, storage)
    return await _load_table_page_from_manifest(
        artifact,
        storage,
        manifest=manifest,
        offset=offset,
        limit=limit,
    )


async def load_table_artifact(
    artifact: ArtifactObject,
    storage: FileStoragePort,
) -> Table:
    if artifact.inline_payload is not None:
        return Table.model_validate(artifact.inline_payload)
    manifest = await load_table_manifest(artifact, storage)
    page = await _load_table_page_from_manifest(
        artifact,
        storage,
        manifest=manifest,
        offset=0,
        limit=max(1, manifest.row_count),
    )
    table = Table(columns=page.columns, rows=page.rows)
    logical_content = table.model_dump_json().encode("utf-8")
    if artifact.byte_size is not None and len(logical_content) != artifact.byte_size:
        raise ResolutionError(
            f"Table artifact {artifact.id} reconstructs to {len(logical_content)} "
            f"bytes, expected {artifact.byte_size}"
        )
    if artifact.sha256 is not None:
        observed_sha256 = sha256(logical_content).hexdigest()
        if observed_sha256 != artifact.sha256:
            raise ResolutionError(
                f"Table artifact {artifact.id} reconstructs to SHA-256 "
                f"{observed_sha256}, expected {artifact.sha256}"
            )
    return table


async def table_artifact_is_accessible(
    artifact: ArtifactObject,
    storage: FileStoragePort,
) -> bool:
    if artifact.inline_payload is not None:
        try:
            Table.model_validate(artifact.inline_payload)
        except ValidationError:
            return False
        return True
    if artifact.bucket is None or artifact.object_key is None:
        return False
    if await storage.stat(artifact.bucket, artifact.object_key) is None:
        return False
    try:
        manifest = await load_table_manifest(artifact, storage)
    except ArtifactContractError:
        return False
    except ResolutionError as exc:
        if isinstance(exc.__cause__, ValueError):
            return False
        raise
    for descriptor in manifest.chunks:
        if await storage.stat(artifact.bucket, descriptor.object_key) is None:
            return False
    return True


def _csv_cell(value: TableValue) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def iter_table_csv(
    artifact: ArtifactObject,
    storage: FileStoragePort,
    *,
    buffer_bytes: int = CSV_EXPORT_BUFFER_BYTES,
) -> AsyncIterator[bytes]:
    """Stream a table artifact as UTF-8 CSV with a BOM and CRLF rows."""

    if artifact.inline_payload is not None:
        table = Table.model_validate(artifact.inline_payload)
        buffer = StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer)
        writer.writerow([column.id for column in table.columns])
        for row in table.rows:
            writer.writerow([_csv_cell(row[column.id]) for column in table.columns])
            if buffer.tell() >= buffer_bytes:
                yield buffer.getvalue().encode("utf-8")
                buffer.seek(0)
                buffer.truncate(0)
        if buffer.tell():
            yield buffer.getvalue().encode("utf-8")
        return

    manifest = await load_table_manifest(artifact, storage)
    if artifact.bucket is None:
        raise ArtifactContractError(
            f"Table artifact {artifact.id} does not have a storage bucket"
        )
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow([column.id for column in manifest.columns])
    for descriptor in manifest.chunks:
        chunk = await load_stored_model(
            storage,
            bucket=artifact.bucket,
            object_key=descriptor.object_key,
            model=TableChunk,
            expected_byte_size=descriptor.byte_size,
            expected_sha256=descriptor.sha256,
        )
        if chunk.offset != descriptor.offset or len(chunk.rows) != descriptor.row_count:
            raise ResolutionError(
                f"Table chunk {descriptor.object_key!r} does not match its manifest "
                f"descriptor for artifact {artifact.id}"
            )
        for row in chunk.rows:
            writer.writerow([_csv_cell(row[column.id]) for column in manifest.columns])
            if buffer.tell() >= buffer_bytes:
                yield buffer.getvalue().encode("utf-8")
                buffer.seek(0)
                buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue().encode("utf-8")


__all__ = [
    "CSV_EXPORT_BUFFER_BYTES",
    "TABLE_CHUNK_ROW_COUNT",
    "TABLE_CHUNK_TARGET_BYTE_SIZE",
    "iter_table_chunks",
    "iter_table_csv",
    "load_table_artifact",
    "load_table_manifest",
    "load_table_page",
    "table_artifact_is_accessible",
]

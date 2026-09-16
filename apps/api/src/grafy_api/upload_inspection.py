"""Inspect stored upload bytes without buffering the whole object."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

import ijson
from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.file_contracts import BLOB_FILE
from grafy_core.ports.storage import ChunkReader, FileStoragePort
from ijson import sendable_list

_READ_CHUNK_BYTES = 1024 * 1024
_JSON_MAX_DEPTH = 64
_JSON_MAX_TOKEN_BYTES = 1024 * 1024


class UploadInspectionError(Exception):
    """Stored upload bytes failed inspection."""


class FileFormatMismatchError(UploadInspectionError):
    """A known extension's bytes disagree with the format that extension names."""

    def __init__(self, filename: str, expected: str) -> None:
        super().__init__(
            f"{filename!r} does not look like a {expected} file. "
            "Rename it or convert it, then try again."
        )
        self.filename = filename
        self.expected = expected


@dataclass(frozen=True, slots=True)
class UploadInspection:
    """Measured size, digest, and resolved file format for one stored upload."""

    byte_size: int
    sha256: str
    artifact_type: ArtifactTypeKey


async def inspect_upload_async(
    *,
    storage: FileStoragePort,
    bucket: str,
    object_key: str,
    original_filename: str,
    expected_size: int,
    max_upload_bytes: int,
    artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
    extension_claims: Mapping[str, ArtifactTypeKey],
    declared_byte_size: int | None = None,
) -> UploadInspection:
    """Stream stored bytes once: count, hash, and confirm format.

    ``declared_byte_size`` is optional storage metadata (e.g. from ``stat``).
    The bytes actually read are authoritative and must agree with both the
    client-declared size and any supplied storage metadata.
    """

    reader = await storage.open_chunks(bucket, object_key)
    try:
        return _inspect_chunks(
            reader,
            original_filename=original_filename,
            expected_size=expected_size,
            max_upload_bytes=max_upload_bytes,
            artifact_types=artifact_types,
            extension_claims=extension_claims,
            declared_byte_size=declared_byte_size,
        )
    finally:
        reader.close()


def _inspect_chunks(
    reader: ChunkReader,
    *,
    original_filename: str,
    expected_size: int,
    max_upload_bytes: int,
    artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
    extension_claims: Mapping[str, ArtifactTypeKey],
    declared_byte_size: int | None,
) -> UploadInspection:
    extension = Path(original_filename).suffix[1:].casefold()
    key = extension_claims.get(extension, BLOB_FILE.key)
    if key != BLOB_FILE.key:
        spec = artifact_types.get((key.id, key.schema_version))
        if spec is None:
            raise UploadInspectionError(
                f"Upload extension {extension!r} maps to artifact type "
                f"{key.id}@{key.schema_version}, which this deployment does "
                "not declare"
            )
    else:
        spec = None

    prefix_needed = _prefix_needed(spec)
    digest = sha256()
    byte_size = 0
    prefix = bytearray()
    json_parser: _IncrementalJsonConfirmer | None = None
    if spec is not None and spec.confirmation_rule.rule in {"json", "json_document"}:
        json_parser = _IncrementalJsonConfirmer(spec.confirmation_rule.rule)

    while True:
        chunk = reader.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        byte_size += len(chunk)
        if byte_size > max_upload_bytes:
            raise UploadInspectionError(
                f"Upload {original_filename!r} exceeds the upload limit of "
                f"{max_upload_bytes} bytes"
            )
        digest.update(chunk)
        if len(prefix) < prefix_needed:
            remaining = prefix_needed - len(prefix)
            prefix.extend(chunk[:remaining])
        if json_parser is not None:
            json_parser.feed(chunk)

    if declared_byte_size is not None and byte_size != declared_byte_size:
        raise UploadInspectionError(
            f"Upload {original_filename!r} storage metadata reported "
            f"{declared_byte_size} bytes but {byte_size} were read"
        )
    if byte_size != expected_size:
        raise UploadInspectionError(
            f"Upload {original_filename!r} declared {expected_size} bytes "
            f"but {byte_size} were stored"
        )

    if spec is not None:
        rule = spec.confirmation_rule
        if rule.rule == "magic":
            if not rule.confirms(bytes(prefix)):
                expected = key.id.removeprefix("file.").upper()
                raise FileFormatMismatchError(original_filename, expected)
        elif json_parser is not None and not json_parser.finish():
            expected = key.id.removeprefix("file.").upper()
            raise FileFormatMismatchError(original_filename, expected)

    return UploadInspection(
        byte_size=byte_size,
        sha256=digest.hexdigest(),
        artifact_type=key,
    )


def _prefix_needed(spec: ArtifactTypeSpec | None) -> int:
    if spec is None or spec.confirmation_rule.rule != "magic":
        return 0
    return max(
        (
            segment.offset + len(segment.value)
            for signature in spec.confirmation_rule.signatures
            for segment in signature.segments
        ),
        default=0,
    )


class _IncrementalJsonConfirmer:
    """Confirm a JSON object or document with bounded event-based parsing."""

    def __init__(self, rule: Literal["json", "json_document"]) -> None:
        self._rule = rule
        self._events = sendable_list()
        self._coro = ijson.basic_parse_coro(self._events)
        self._depth = 0
        self._root: type | None = None
        self._failed = False
        self._finished = False

    def feed(self, chunk: bytes) -> None:
        if self._failed or self._finished:
            return
        try:
            self._coro.send(chunk)
            self._consume_events()
        except StopIteration:
            self._consume_events()
            self._finished = True
        except (ijson.JSONError, UnicodeDecodeError, ValueError):
            self._failed = True

    def finish(self) -> bool:
        if not self._finished and not self._failed:
            self.feed(b"")
            if not self._finished and not self._failed:
                try:
                    self._coro.close()
                except Exception:
                    self._failed = True
                self._finished = True
        if self._failed or self._root is None:
            return False
        if self._rule == "json":
            return self._root is dict
        return self._root in {dict, list}

    def _consume_events(self) -> None:
        while self._events:
            event, value = self._events.pop(0)
            if event == "start_map":
                self._enter(dict)
            elif event == "start_array":
                self._enter(list)
            elif event in {"end_map", "end_array"}:
                self._depth -= 1
            elif event in {"string", "number", "boolean", "null"}:
                self._check_token(event, value)
                if self._depth == 0 and self._root is None:
                    self._root = type(None) if value is None else type(value)
            elif event == "map_key":
                self._check_token("string", value)

    def _enter(self, root_type: type) -> None:
        if self._depth == 0:
            self._root = root_type
        self._depth += 1
        if self._depth > _JSON_MAX_DEPTH:
            raise ValueError("JSON nesting exceeds the configured limit")

    def _check_token(self, event: str, value: object) -> None:
        if event == "string" and isinstance(value, str):
            if len(value.encode("utf-8")) > _JSON_MAX_TOKEN_BYTES:
                raise ValueError("JSON token exceeds the configured limit")
        if event == "number" and isinstance(value, (int, float)):
            if len(str(value).encode("utf-8")) > _JSON_MAX_TOKEN_BYTES:
                raise ValueError("JSON token exceeds the configured limit")

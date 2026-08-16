"""Validation and indexing for immutable generated-node source bundles."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import PurePosixPath
import tarfile
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from grafy_core.domain.agent_authoring import (
    CapabilityManifest,
    GeneratedNodeManifest,
    RuntimeArtifactReference,
)


MAX_SOURCE_BUNDLE_BYTES = 67_108_864
MAX_SOURCE_BUNDLE_FILES = 2_000
MAX_SOURCE_BUNDLE_MEMBERS = 4_000
MAX_SOURCE_FILE_BYTES = 8_388_608
MAX_SOURCE_TREE_BYTES = 67_108_864


class SourceBundleError(ValueError):
    pass


class SourceBundleFile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    path: str
    content: bytes = Field(repr=False)
    byte_count: int = Field(ge=0, le=MAX_SOURCE_FILE_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceBundleIndex(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_byte_count: int = Field(ge=1, le=MAX_SOURCE_BUNDLE_BYTES)
    uncompressed_byte_count: int = Field(ge=1, le=MAX_SOURCE_TREE_BYTES)
    files: tuple[SourceBundleFile, ...] = Field(
        min_length=4,
        max_length=MAX_SOURCE_BUNDLE_FILES,
    )

    def file(self, path: str) -> SourceBundleFile:
        for item in self.files:
            if item.path == path:
                return item
        raise SourceBundleError(f"Source bundle does not contain {path!r}")


class GeneratedNodeSourceDefinition(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    manifest: GeneratedNodeManifest
    capabilities: CapabilityManifest


class GeneratedNodeBuildDocument(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tests_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: GeneratedNodeManifest
    capabilities: CapabilityManifest
    runtime_image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_artifact: RuntimeArtifactReference

    @property
    def digest(self) -> str:
        return sha256(
            json.dumps(
                self.model_dump(mode="json", exclude_none=False, by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def read_source_bundle(archive: bytes) -> SourceBundleIndex:
    """Read a bounded, reviewable tar.gz without extracting it to a filesystem."""

    if not archive or len(archive) > MAX_SOURCE_BUNDLE_BYTES:
        raise SourceBundleError(
            f"Source bundle must contain 1 to {MAX_SOURCE_BUNDLE_BYTES} bytes"
        )
    files: dict[str, SourceBundleFile] = {}
    uncompressed_bytes = 0
    member_count = 0
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as bundle:
            for member in bundle:
                member_count += 1
                if member_count > MAX_SOURCE_BUNDLE_MEMBERS:
                    raise SourceBundleError(
                        f"Source bundle exceeds {MAX_SOURCE_BUNDLE_MEMBERS} entries"
                    )
                if member.isdir():
                    continue
                if not member.isfile():
                    raise SourceBundleError(
                        f"Source bundle contains unsupported entry {member.name!r}"
                    )
                path = _normalized_bundle_path(member.name)
                if path in files:
                    raise SourceBundleError(
                        f"Source bundle contains duplicate path {path!r}"
                    )
                if not _allowed_source_path(path):
                    raise SourceBundleError(
                        f"Source bundle contains non-reviewable path {path!r}"
                    )
                if member.size < 0 or member.size > MAX_SOURCE_FILE_BYTES:
                    raise SourceBundleError(
                        f"Source bundle file {path!r} exceeds {MAX_SOURCE_FILE_BYTES} bytes"
                    )
                uncompressed_bytes += member.size
                if uncompressed_bytes > MAX_SOURCE_TREE_BYTES:
                    raise SourceBundleError(
                        "Source bundle exceeds the uncompressed byte limit"
                    )
                if len(files) >= MAX_SOURCE_BUNDLE_FILES:
                    raise SourceBundleError(
                        f"Source bundle exceeds {MAX_SOURCE_BUNDLE_FILES} files"
                    )
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise SourceBundleError(
                        f"Source bundle entry {path!r} has no content"
                    )
                content = extracted.read(member.size + 1)
                if len(content) != member.size:
                    raise SourceBundleError(
                        f"Source bundle entry {path!r} size does not match its header"
                    )
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceBundleError(
                        f"Source bundle entry {path!r} is not valid UTF-8"
                    ) from exc
                files[path] = SourceBundleFile(
                    path=path,
                    content=content,
                    byte_count=len(content),
                    sha256=sha256(content).hexdigest(),
                )
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise SourceBundleError("Source bundle is not a valid tar.gz archive") from exc

    for required in ("pyproject.toml", "uv.lock", "node.json", "src/node.py"):
        if required not in files or files[required].byte_count == 0:
            raise SourceBundleError(f"Source bundle is missing non-empty {required!r}")
    if not any(path.startswith("tests/") and path.endswith(".py") for path in files):
        raise SourceBundleError("Source bundle must contain Python tests")
    return SourceBundleIndex(
        archive_sha256=sha256(archive).hexdigest(),
        archive_byte_count=len(archive),
        uncompressed_byte_count=uncompressed_bytes,
        files=tuple(files[path] for path in sorted(files)),
    )


def digest_source_subset(
    index: SourceBundleIndex,
    *,
    prefix: str,
) -> str:
    hasher = sha256()
    found = False
    for item in index.files:
        if not item.path.startswith(prefix):
            continue
        found = True
        hasher.update(item.path.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(item.content)
        hasher.update(b"\x00")
    if not found:
        raise SourceBundleError(f"Source bundle contains no files below {prefix!r}")
    return hasher.hexdigest()


def _normalized_bundle_path(value: str) -> str:
    candidate = value[2:] if value.startswith("./") else value
    path = PurePosixPath(candidate)
    if (
        candidate == ""
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != candidate
    ):
        raise SourceBundleError(f"Source bundle contains unsafe path {value!r}")
    return candidate


def _allowed_source_path(path: str) -> bool:
    if path in {"pyproject.toml", "uv.lock", "node.json"}:
        return True
    return (path.startswith("src/") or path.startswith("tests/")) and path.endswith(
        ".py"
    )


__all__ = [
    "MAX_SOURCE_BUNDLE_BYTES",
    "MAX_SOURCE_BUNDLE_FILES",
    "MAX_SOURCE_BUNDLE_MEMBERS",
    "MAX_SOURCE_FILE_BYTES",
    "MAX_SOURCE_TREE_BYTES",
    "GeneratedNodeBuildDocument",
    "GeneratedNodeSourceDefinition",
    "SourceBundleError",
    "SourceBundleFile",
    "SourceBundleIndex",
    "digest_source_subset",
    "read_source_bundle",
]

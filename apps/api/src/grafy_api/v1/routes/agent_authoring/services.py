import asyncio
from dataclasses import dataclass
from difflib import unified_diff
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from grafy_core.domain.agent_authoring import (
    BuildArtifactSet,
    CapabilityManifest,
    GeneratedNodeManifest,
    NodeBuildAttempt,
    NodeRelease,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.source_bundles import (
    GeneratedNodeBuildDocument,
    GeneratedNodeSourceDefinition,
    MAX_SOURCE_BUNDLE_BYTES,
    SourceBundleError,
    SourceBundleIndex,
    digest_source_subset,
    read_source_bundle,
)


BuildReviewFileKind = Literal[
    "project",
    "lockfile",
    "manifest",
    "implementation",
    "test",
]
BuildReviewChangeKind = Literal["added", "modified", "removed"]

_MAX_DIFF_INPUT_BYTES = 1_048_576
_MAX_TOTAL_DIFF_BYTES = 1_048_576


class BuildReviewError(ValueError):
    """A build cannot be presented safely for human review."""


class BuildReviewFileNotFoundError(BuildReviewError):
    """The requested curated source file is absent from the build."""


@dataclass(frozen=True, slots=True)
class VerifiedBuildReviewFile:
    path: str
    kind: BuildReviewFileKind
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedBuildReview:
    build_attempt_id: UUID
    source_digest: str
    archive_byte_count: int
    uncompressed_byte_count: int
    lock_digest: str
    tests_digest: str
    implementation_digest: str
    tests_passed: bool
    previous_release_revision: int | None
    files: tuple[VerifiedBuildReviewFile, ...]
    changes: tuple["VerifiedBuildReviewChange", ...]


@dataclass(frozen=True, slots=True)
class VerifiedBuildReviewChange:
    path: str
    kind: BuildReviewFileKind
    change: BuildReviewChangeKind
    previous_sha256: str | None
    current_sha256: str | None
    unified_diff: str | None
    diff_truncated: bool


@dataclass(frozen=True, slots=True)
class VerifiedBuildReviewContent:
    path: str
    kind: BuildReviewFileKind
    byte_count: int
    sha256: str
    content: str


class BuildReviewService:
    """Loads immutable build bundles and verifies every approval-facing digest."""

    def __init__(self, storage: FileStoragePort, bucket: str) -> None:
        self._storage = storage
        self._bucket = bucket

    async def review(
        self,
        build: NodeBuildAttempt,
        previous_release: NodeRelease | None = None,
    ) -> VerifiedBuildReview:
        index = await self._reviewable_index(build)
        artifacts = build.artifacts
        if artifacts is None:
            raise BuildReviewError(
                f"Build {build.id} has no source artifacts to review"
            )
        previous_index = None
        if previous_release is not None:
            previous_index = await self._verified_artifact_index(
                owner=f"release {previous_release.node_id}@{previous_release.revision}",
                artifacts=previous_release.artifacts,
                expected_source_bundle_key=(
                    f"generated-nodes/{previous_release.workspace_id}/"
                    f"{previous_release.draft_node_id}/sources/"
                    f"{previous_release.artifacts.source_digest}.tar.gz"
                ),
            )
            _verify_definition_and_build_digest(
                owner=(
                    f"Release {previous_release.node_id}@"
                    f"{previous_release.revision}"
                ),
                index=previous_index,
                manifest=previous_release.manifest,
                capabilities=previous_release.capabilities,
                artifacts=previous_release.artifacts,
            )
            if (
                previous_release.capability_digest
                != previous_release.capabilities.digest
            ):
                raise BuildReviewError(
                    f"Release {previous_release.node_id}@"
                    f"{previous_release.revision} capability digest does not "
                    "match its manifest"
                )
        return VerifiedBuildReview(
            build_attempt_id=build.id,
            source_digest=index.archive_sha256,
            archive_byte_count=index.archive_byte_count,
            uncompressed_byte_count=index.uncompressed_byte_count,
            lock_digest=artifacts.lock_digest,
            tests_digest=artifacts.tests_digest,
            implementation_digest=artifacts.implementation_digest,
            tests_passed=artifacts.tests_passed,
            previous_release_revision=(
                previous_release.revision
                if previous_release is not None
                else None
            ),
            files=tuple(
                VerifiedBuildReviewFile(
                    path=file.path,
                    kind=_file_kind(file.path),
                    byte_count=file.byte_count,
                    sha256=file.sha256,
                )
                for file in index.files
            ),
            changes=_source_changes(index, previous_index),
        )

    async def file(
        self,
        build: NodeBuildAttempt,
        path: str,
    ) -> VerifiedBuildReviewContent:
        index = await self._reviewable_index(build)
        try:
            file = index.file(path)
        except SourceBundleError as exc:
            raise BuildReviewFileNotFoundError(
                f"Build {build.id} has no reviewable source file {path!r}"
            ) from exc
        return VerifiedBuildReviewContent(
            path=file.path,
            kind=_file_kind(file.path),
            byte_count=file.byte_count,
            sha256=file.sha256,
            content=file.content.decode("utf-8"),
        )

    async def _verified_index(self, build: NodeBuildAttempt) -> SourceBundleIndex:
        artifacts = build.artifacts
        if artifacts is None:
            raise BuildReviewError(
                f"Build {build.id} has no source artifacts to review"
            )
        return await self._verified_artifact_index(
            owner=f"build {build.id}",
            artifacts=artifacts,
            expected_source_bundle_key=(
                f"generated-nodes/{build.workspace_id}/{build.draft_node_id}/"
                f"sources/{artifacts.source_digest}.tar.gz"
            ),
        )

    async def _reviewable_index(
        self,
        build: NodeBuildAttempt,
    ) -> SourceBundleIndex:
        if build.manifest is None or build.capabilities is None:
            raise BuildReviewError(
                f"Build {build.id} has no generated-node definition to review"
            )
        index = await self._verified_index(build)
        artifacts = build.artifacts
        if artifacts is None:
            raise BuildReviewError(
                f"Build {build.id} has no source artifacts to review"
            )
        _verify_definition_and_build_digest(
            owner=f"Build {build.id}",
            index=index,
            manifest=build.manifest,
            capabilities=build.capabilities,
            artifacts=artifacts,
        )
        if build.capability_digest != build.capabilities.digest:
            raise BuildReviewError(
                f"Build {build.id} capability digest does not match its manifest"
            )
        return index

    async def _verified_artifact_index(
        self,
        *,
        owner: str,
        artifacts: BuildArtifactSet,
        expected_source_bundle_key: str,
    ) -> SourceBundleIndex:
        if artifacts.source_bundle_key != expected_source_bundle_key:
            raise BuildReviewError(
                f"{owner.capitalize()} source bundle key is outside its "
                "immutable build namespace"
            )
        stored = await self._storage.stat(
            self._bucket,
            artifacts.source_bundle_key,
        )
        if stored is None:
            raise BuildReviewError(
                f"{owner.capitalize()} source bundle is unavailable"
            )
        if stored.byte_size > MAX_SOURCE_BUNDLE_BYTES:
            raise BuildReviewError(
                f"{owner.capitalize()} source bundle exceeds the review limit"
            )
        try:
            stream = await self._storage.load(
                self._bucket,
                artifacts.source_bundle_key,
            )
        except FileNotFoundError as exc:
            raise BuildReviewError(
                f"{owner.capitalize()} source bundle is unavailable"
            ) from exc
        try:
            archive = await asyncio.to_thread(
                stream.read,
                MAX_SOURCE_BUNDLE_BYTES + 1,
            )
        finally:
            stream.close()
        try:
            index = await asyncio.to_thread(read_source_bundle, archive)
            tests_digest = digest_source_subset(index, prefix="tests/")
            implementation_digest = digest_source_subset(index, prefix="src/")
        except SourceBundleError as exc:
            raise BuildReviewError(
                f"{owner.capitalize()} source bundle is not reviewable: {exc}"
            ) from exc
        lock_digest = index.file("uv.lock").sha256
        if (
            index.archive_sha256 != artifacts.source_digest
            or lock_digest != artifacts.lock_digest
            or tests_digest != artifacts.tests_digest
            or implementation_digest != artifacts.implementation_digest
        ):
            raise BuildReviewError(
                f"{owner.capitalize()} source bundle does not match its recorded "
                "digests"
            )
        return index


def _file_kind(path: str) -> BuildReviewFileKind:
    if path == "pyproject.toml":
        return "project"
    if path == "uv.lock":
        return "lockfile"
    if path == "node.json":
        return "manifest"
    if path.startswith("tests/"):
        return "test"
    return "implementation"


def _verify_definition_and_build_digest(
    *,
    owner: str,
    index: SourceBundleIndex,
    manifest: GeneratedNodeManifest,
    capabilities: CapabilityManifest,
    artifacts: BuildArtifactSet,
) -> None:
    try:
        definition = GeneratedNodeSourceDefinition.model_validate_json(
            index.file("node.json").content
        )
    except (SourceBundleError, ValidationError) as exc:
        raise BuildReviewError(
            f"{owner} node.json is not a valid generated-node definition"
        ) from exc
    if definition.manifest != manifest or definition.capabilities != capabilities:
        raise BuildReviewError(
            f"{owner} node.json does not match the persisted build definition"
        )
    build_document = GeneratedNodeBuildDocument(
        source_digest=artifacts.source_digest,
        lock_digest=artifacts.lock_digest,
        tests_digest=artifacts.tests_digest,
        implementation_digest=artifacts.implementation_digest,
        manifest=manifest,
        capabilities=capabilities,
        runtime_image_digest=artifacts.runtime_image_digest,
        profile_digest=artifacts.profile_digest,
        runtime_artifact=artifacts.runtime_artifact,
    )
    if build_document.digest != artifacts.build_digest:
        raise BuildReviewError(
            f"{owner} build digest does not match its canonical build document"
        )


def _source_changes(
    current: SourceBundleIndex,
    previous: SourceBundleIndex | None,
) -> tuple[VerifiedBuildReviewChange, ...]:
    current_files = {file.path: file for file in current.files}
    previous_files = (
        {file.path: file for file in previous.files}
        if previous is not None
        else {}
    )
    remaining_diff_bytes = _MAX_TOTAL_DIFF_BYTES
    changes: list[VerifiedBuildReviewChange] = []
    for path in sorted(current_files.keys() | previous_files.keys()):
        current_file = current_files.get(path)
        previous_file = previous_files.get(path)
        if (
            current_file is not None
            and previous_file is not None
            and current_file.sha256 == previous_file.sha256
        ):
            continue
        change: BuildReviewChangeKind = "modified"
        if previous_file is None:
            change = "added"
        elif current_file is None:
            change = "removed"
        previous_content = previous_file.content if previous_file is not None else b""
        current_content = current_file.content if current_file is not None else b""
        diff_text: str | None = None
        diff_truncated = False
        if len(previous_content) + len(current_content) > _MAX_DIFF_INPUT_BYTES:
            diff_truncated = True
        elif remaining_diff_bytes <= 0:
            diff_truncated = True
        else:
            lines = unified_diff(
                previous_content.decode("utf-8").splitlines(keepends=True),
                current_content.decode("utf-8").splitlines(keepends=True),
                fromfile=f"previous/{path}",
                tofile=f"current/{path}",
            )
            chunks: list[str] = []
            used_bytes = 0
            for line in lines:
                line_bytes = len(line.encode("utf-8"))
                if used_bytes + line_bytes > remaining_diff_bytes:
                    diff_truncated = True
                    break
                chunks.append(line)
                used_bytes += line_bytes
            diff_text = "".join(chunks)
            remaining_diff_bytes -= used_bytes
        changes.append(
            VerifiedBuildReviewChange(
                path=path,
                kind=_file_kind(path),
                change=change,
                previous_sha256=(
                    previous_file.sha256 if previous_file is not None else None
                ),
                current_sha256=(
                    current_file.sha256 if current_file is not None else None
                ),
                unified_diff=diff_text,
                diff_truncated=diff_truncated,
            )
        )
    return tuple(changes)


__all__ = [
    "BuildReviewError",
    "BuildReviewChangeKind",
    "BuildReviewFileKind",
    "BuildReviewFileNotFoundError",
    "BuildReviewService",
    "VerifiedBuildReview",
    "VerifiedBuildReviewContent",
    "VerifiedBuildReviewChange",
    "VerifiedBuildReviewFile",
]

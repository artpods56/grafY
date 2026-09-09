"""Reserved working-copy workflow shared by coding-agent Plugin authoring."""

import difflib
from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Literal
from uuid import UUID, uuid7

from pydantic import BaseModel, Field

from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.ports.storage import FileStoragePort

from grafy_api.plugins.publication.workflow import (
    PluginPublicationWorkflow,
    render_plugin_capability_diff,
)
from grafy_api.plugins.publication.source import (
    build_deterministic_archive,
    scan_source_tree,
    source_archive_entries,
)


_PLUGIN_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_OPERATOR_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_REVIEW_DIFF_LIMIT = 64 * 1_024


class PluginAuthoringError(RuntimeError):
    """A Plugin working-copy authoring operation could not be completed."""


class PluginAuthoringConflictError(PluginAuthoringError):
    """A different authoring session already owns the working copy."""


class PluginAuthoringReservation(BaseModel):
    session_id: UUID
    workspace_id: UUID
    slug: str
    actor_user_id: UUID
    project_directory: Path
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    reviewed_source_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    reviewed_base_revision: int | None = Field(default=None, ge=0)


class PluginSourceChange(BaseModel):
    path: str
    kind: Literal["added", "modified", "deleted"]


class PluginAuthoringReview(BaseModel):
    session_id: UUID
    workspace_id: UUID
    slug: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_revision: int | None = Field(default=None, ge=1)
    changes: tuple[PluginSourceChange, ...]
    unified_diff: str
    lock_changed: bool
    node_contract_changed: bool
    artifact_contract_changed: bool
    capabilities_changed: bool
    runtime_profile_changed: bool
    network_authority_changes: tuple[str, ...] = ()


class PluginAuthoringService:
    """Own deterministic scaffolding, reservation, review, and agent publish."""

    def __init__(
        self,
        *,
        authoring_root: Path,
        allowed_roots: tuple[Path, ...],
        sdk_project: Path,
        publication: PluginPublicationWorkflow,
        releases: PluginReleaseService,
        storage: FileStoragePort,
        bucket: str,
        uv_binary: str = "uv",
    ) -> None:
        self._authoring_root = authoring_root.expanduser().resolve()
        resolved_roots = tuple(root.expanduser().resolve() for root in allowed_roots)
        if not any(
            self._authoring_root == root or self._authoring_root.is_relative_to(root)
            for root in resolved_roots
        ):
            raise PluginAuthoringError(
                "Plugin authoring root must be beneath a configured Plugin root"
            )
        self._authoring_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._sdk_project = sdk_project.expanduser().resolve()
        self._publication = publication
        self._releases = releases
        self._storage = storage
        self._bucket = bucket
        self._uv_binary = uv_binary

    def reserve(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        actor_user_id: UUID,
    ) -> PluginAuthoringReservation:
        project = self._project(workspace_id, slug, must_exist=True)
        source_digest = self._source_digest(project)
        reservation = PluginAuthoringReservation(
            session_id=uuid7(),
            workspace_id=workspace_id,
            slug=slug,
            actor_user_id=actor_user_id,
            project_directory=project,
            source_digest=source_digest,
            created_at=datetime.now(UTC),
        )
        reservation_path = self._reservation_path(project)
        reservation_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(
                reservation_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise PluginAuthoringConflictError(
                f"Plugin working copy {slug!r} already has an active authoring session"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(reservation.model_dump_json(indent=2) + "\n")
        return reservation

    def scaffold(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        operator_slug: str,
        title: str,
        actor_user_id: UUID,
    ) -> PluginAuthoringReservation:
        self._validate_identity(slug, operator_slug, title)
        workspace_root = self._workspace_root(workspace_id)
        workspace_root.mkdir(mode=0o700, exist_ok=True)
        project = self._project(workspace_id, slug, must_exist=False)
        try:
            project.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise PluginAuthoringConflictError(
                f"Plugin working copy {slug!r} already exists; reserve it explicitly"
            ) from exc
        try:
            wheel = self._build_sdk_wheel(project)
            self._write_scaffold(project, slug, operator_slug, title, wheel.name)
            self._run_uv(
                ("lock", "--project", str(project)),
                project,
                "dependency lock",
            )
            return self.reserve(
                workspace_id=workspace_id,
                slug=slug,
                actor_user_id=actor_user_id,
            )
        except BaseException:
            shutil.rmtree(project, ignore_errors=True)
            raise

    async def review(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        actor_user_id: UUID,
        session_id: UUID,
    ) -> PluginAuthoringReview:
        await self._releases.authorize_publisher(workspace_id, actor_user_id)
        reservation = self._require_reservation(
            workspace_id=workspace_id,
            slug=slug,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
        verified = await self._publication.verify(
            reservation.project_directory,
            expected_slug=slug,
        )
        source_digest = sha256(verified.source_archive).hexdigest()
        current_entries = source_archive_entries(verified.source_archive)
        latest = next(
            (
                release
                for release in await self._releases.list_current(workspace_id)
                if release.release.slug == slug
            ),
            None,
        )
        base_entries: dict[str, bytes] = {}
        if latest is not None:
            try:
                stream = await self._storage.load(
                    self._bucket,
                    latest.source_object_key,
                )
                try:
                    base_entries = source_archive_entries(stream.read())
                finally:
                    stream.close()
            except Exception as exc:
                raise PluginAuthoringError(
                    f"Could not load Plugin {slug!r} release {latest.release.revision} "
                    "for review"
                ) from exc
        changes, unified_diff = _source_diff(base_entries, current_entries)
        review = PluginAuthoringReview(
            session_id=session_id,
            workspace_id=workspace_id,
            slug=slug,
            source_digest=source_digest,
            base_revision=None if latest is None else latest.release.revision,
            changes=changes,
            unified_diff=unified_diff,
            lock_changed=(
                latest is None or latest.release.lock_digest != verified.lock_digest
            ),
            node_contract_changed=(
                latest is None or latest.release.catalog.nodes != verified.catalog.nodes
            ),
            artifact_contract_changed=(
                latest is None
                or latest.release.catalog.artifact_types
                != verified.catalog.artifact_types
            ),
            capabilities_changed=(
                latest is None or latest.release.capabilities != verified.capabilities
            ),
            runtime_profile_changed=(
                latest is None
                or latest.release.runtime_profile != verified.runtime_profile
            ),
            network_authority_changes=render_plugin_capability_diff(
                None if latest is None else latest.release.catalog,
                verified.catalog,
            ),
        )
        self._write_reservation(
            reservation.model_copy(
                update={
                    "source_digest": source_digest,
                    "reviewed_source_digest": source_digest,
                    "reviewed_base_revision": review.base_revision or 0,
                }
            )
        )
        return review

    async def publish(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        actor_user_id: UUID,
        session_id: UUID,
    ) -> InstalledPluginRelease:
        reservation = self._require_reservation(
            workspace_id=workspace_id,
            slug=slug,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
        if reservation.reviewed_source_digest is None:
            raise PluginAuthoringConflictError(
                "Plugin working copy must pass review before agent publication"
            )
        release = await self._publication.publish(
            workspace_id=workspace_id,
            directory=reservation.project_directory,
            expected_slug=slug,
            published_by_user_id=actor_user_id,
            reviewed_source_digest=reservation.reviewed_source_digest,
            reviewed_base_revision=reservation.reviewed_base_revision,
        )
        self.release(
            workspace_id=workspace_id,
            slug=slug,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
        return release

    def release(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        actor_user_id: UUID,
        session_id: UUID,
    ) -> None:
        reservation = self._require_reservation(
            workspace_id=workspace_id,
            slug=slug,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
        self._reservation_path(reservation.project_directory).unlink()

    def _workspace_root(self, workspace_id: UUID) -> Path:
        workspace_root = (self._authoring_root / str(workspace_id)).resolve()
        if workspace_root.parent != self._authoring_root:
            raise PluginAuthoringError(
                "Plugin Workspace path escapes the configured authoring root"
            )
        return workspace_root

    def _project(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        must_exist: bool,
    ) -> Path:
        self._validate_slug(slug)
        workspace_root = self._workspace_root(workspace_id)
        candidate = workspace_root / slug
        project = candidate.resolve(strict=must_exist)
        if project.parent != workspace_root:
            raise PluginAuthoringError(
                "Plugin working-copy path escapes the configured authoring root"
            )
        if must_exist and not project.is_dir():
            raise PluginAuthoringError(
                f"Plugin working copy {slug!r} is not a directory"
            )
        return project

    def _require_reservation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        actor_user_id: UUID,
        session_id: UUID,
    ) -> PluginAuthoringReservation:
        project = self._project(workspace_id, slug, must_exist=True)
        path = self._reservation_path(project)
        try:
            reservation = PluginAuthoringReservation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise PluginAuthoringConflictError(
                f"Plugin working copy {slug!r} has no active authoring session"
            ) from exc
        except Exception as exc:
            raise PluginAuthoringError(
                f"Plugin working copy {slug!r} has an invalid reservation"
            ) from exc
        if (
            reservation.workspace_id != workspace_id
            or reservation.slug != slug
            or reservation.actor_user_id != actor_user_id
            or reservation.session_id != session_id
            or reservation.project_directory != project
        ):
            raise PluginAuthoringConflictError(
                f"Plugin working copy {slug!r} is owned by another authoring session"
            )
        return reservation

    def _write_reservation(self, reservation: PluginAuthoringReservation) -> None:
        path = self._reservation_path(reservation.project_directory)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            reservation.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def _build_sdk_wheel(self, project: Path) -> Path:
        if not self._sdk_project.is_dir():
            raise PluginAuthoringError(
                "Configured Grafy Plugin SDK project is unavailable"
            )
        wheel_directory = project / "wheels"
        wheel_directory.mkdir(mode=0o700)
        with tempfile.TemporaryDirectory(
            prefix="grafy-plugin-sdk-build-"
        ) as temporary_directory:
            sdk_copy = Path(temporary_directory) / "sdk"
            shutil.copytree(
                self._sdk_project,
                sdk_copy,
                ignore=shutil.ignore_patterns(
                    ".venv",
                    "__pycache__",
                    "*.egg-info",
                    "build",
                ),
            )
            self._run_uv(
                (
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(wheel_directory),
                    str(sdk_copy),
                ),
                sdk_copy,
                "SDK wheel build",
            )
        wheels = sorted(wheel_directory.glob("grafy_core-*.whl"))
        if len(wheels) != 1:
            raise PluginAuthoringError(
                "SDK wheel build did not produce exactly one grafy-core wheel"
            )
        return wheels[0]

    def _run_uv(
        self,
        arguments: tuple[str, ...],
        working_directory: Path,
        operation: str,
    ) -> None:
        environment = {
            "HOME": tempfile.mkdtemp(prefix="grafy-plugin-authoring-home-"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.environ.get("PATH", ""),
            "UV_DEFAULT_INDEX": "https://pypi.org/simple",
            "UV_NO_CONFIG": "1",
            "UV_NO_PROGRESS": "1",
        }
        try:
            completed = subprocess.run(
                (self._uv_binary, *arguments),
                cwd=working_directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PluginAuthoringError(f"Plugin {operation} could not run") from exc
        finally:
            shutil.rmtree(environment["HOME"], ignore_errors=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-4_000:]
            raise PluginAuthoringError(
                f"Plugin {operation} failed with exit code "
                f"{completed.returncode}: {detail}"
            )

    def _write_scaffold(
        self,
        project: Path,
        slug: str,
        operator_slug: str,
        title: str,
        wheel_name: str,
    ) -> None:
        package = project / "src" / "grafy_plugin"
        tests = project / "tests"
        package.mkdir(parents=True)
        tests.mkdir()
        distribution_slug = slug.replace(".", "-")
        (project / "pyproject.toml").write_text(
            _pyproject(distribution_slug, wheel_name),
            encoding="utf-8",
        )
        (project / "README.md").write_text(
            f"# {title}\n\nGrafy Workspace Plugin `{slug}`.\n",
            encoding="utf-8",
        )
        (package / "declaration.py").write_text(
            "from grafy_core.artifact_contracts import TEXT_VALUE\n"
            "from grafy_core.plugins import Plugin\n\n\n"
            f"PLUGIN = Plugin(slug={slug!r}, title={title!r})\n"
            "PLUGIN.register_artifact_type_dependency(TEXT_VALUE)\n",
            encoding="utf-8",
        )
        operator_id = f"{slug}.{operator_slug}"
        (package / "nodes.py").write_text(
            _node_module(operator_id, title),
            encoding="utf-8",
        )
        (package / "__init__.py").write_text(
            "from grafy_plugin.declaration import PLUGIN\n"
            "from grafy_plugin.nodes import generate_text\n\n"
            '__all__ = ["PLUGIN", "generate_text"]\n',
            encoding="utf-8",
        )
        (package / "py.typed").write_bytes(b"")
        (tests / "test_plugin.py").write_text(
            "from grafy_plugin import PLUGIN\n\n\n"
            "def test_plugin_contract() -> None:\n"
            f"    assert PLUGIN.slug == {slug!r}\n"
            f"    assert [node.key for node in PLUGIN.nodes] == "
            f"[{(operator_id, 1)!r}]\n",
            encoding="utf-8",
        )

    @staticmethod
    def _reservation_path(project: Path) -> Path:
        return project / ".grafy" / "authoring.json"

    @staticmethod
    def _source_digest(project: Path) -> str:
        return sha256(
            build_deterministic_archive(scan_source_tree(project))
        ).hexdigest()

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if len(slug) > 100 or _PLUGIN_SLUG.fullmatch(slug) is None:
            raise PluginAuthoringError(f"Invalid Plugin slug {slug!r}")

    @classmethod
    def _validate_identity(cls, slug: str, operator_slug: str, title: str) -> None:
        cls._validate_slug(slug)
        if len(operator_slug) > 100 or _OPERATOR_SLUG.fullmatch(operator_slug) is None:
            raise PluginAuthoringError(
                f"Invalid Plugin operator slug {operator_slug!r}"
            )
        if title.strip() != title or not title or len(title) > 160:
            raise PluginAuthoringError(
                "Plugin title must contain 1 to 160 trimmed characters"
            )


def _source_diff(
    base: dict[str, bytes],
    current: dict[str, bytes],
) -> tuple[tuple[PluginSourceChange, ...], str]:
    changes: list[PluginSourceChange] = []
    diff_lines: list[str] = []
    for path in sorted(set(base) | set(current)):
        before = base.get(path)
        after = current.get(path)
        if before == after:
            continue
        kind: Literal["added", "modified", "deleted"]
        if before is None:
            kind = "added"
        elif after is None:
            kind = "deleted"
        else:
            kind = "modified"
        changes.append(PluginSourceChange(path=path, kind=kind))
        try:
            before_lines = (
                []
                if before is None
                else before.decode("utf-8").splitlines(keepends=True)
            )
            after_lines = (
                [] if after is None else after.decode("utf-8").splitlines(keepends=True)
            )
        except UnicodeDecodeError:
            diff_lines.append(f"Binary file {path} changed\n")
            continue
        diff_lines.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"release/{path}",
                tofile=f"working-copy/{path}",
            )
        )
    rendered = "".join(diff_lines)
    if len(rendered.encode("utf-8")) > _REVIEW_DIFF_LIMIT:
        encoded = rendered.encode("utf-8")[:_REVIEW_DIFF_LIMIT]
        rendered = encoded.decode("utf-8", errors="ignore") + "\n… diff truncated …\n"
    return tuple(changes), rendered


def _pyproject(distribution_slug: str, wheel_name: str) -> str:
    return f"""[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "grafy-plugin-{distribution_slug}"
version = "0.1.0"
requires-python = "==3.14.*"
dependencies = ["grafy-core==0.1.0"]
description = "Agent-authored Grafy Workspace Plugin"

[tool.uv.sources]
grafy-core = {{ path = "wheels/{wheel_name}" }}

[dependency-groups]
dev = ["pytest>=8.4.2", "pytest-asyncio>=1.3.0"]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.setuptools]
package-dir = {{ "" = "src" }}

[tool.setuptools.packages.find]
where = ["src"]
"""


def _node_module(operator_id: str, title: str) -> str:
    return f"""from typing import Annotated

from grafy_core.artifacts import NoConfig, NodeInput, NodeOutput
from grafy_core.nodes import OutPort
from grafy_core.artifact_contracts import TEXT_VALUE, TextValue

from grafy_plugin.declaration import PLUGIN


class GenerateTextOutput(NodeOutput):
    text: Annotated[TextValue, OutPort(TEXT_VALUE)]


@PLUGIN.function_node(
    operator_id={operator_id!r},
    version=1,
    title={title!r},
)
async def generate_text(
    _config: NoConfig,
    _inputs: NodeInput,
) -> GenerateTextOutput:
    return GenerateTextOutput(text=TextValue(value={title!r}))
"""


__all__ = [
    "PluginAuthoringConflictError",
    "PluginAuthoringError",
    "PluginAuthoringReservation",
    "PluginAuthoringReview",
    "PluginAuthoringService",
    "PluginSourceChange",
]

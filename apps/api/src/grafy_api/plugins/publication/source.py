"""Verify and freeze a human-authored uv Plugin directory."""

from collections.abc import Sequence
from dataclasses import dataclass
import gzip
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from typing import cast

from pydantic import ValidationError

from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    plugin_contract_digest,
    plugin_profile_digest,
)
from grafy_core.plugin_inspector import InspectionResult
from grafy_core.runtime.plugin_loader import (
    WORKSPACE_PLUGIN_LOADER_TARGET,
    split_plugin_loader_target,
)


MAX_PLUGIN_SOURCE_FILES = 2_000
MAX_PLUGIN_SOURCE_FILE_BYTES = 8 * 1024 * 1024
MAX_PLUGIN_SOURCE_BYTES = 64 * 1024 * 1024

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".venv",
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".grafy",
    }
)

SUBPROCESS_TIMEOUT_SECONDS = 600


class PluginPublishingError(RuntimeError):
    """A Plugin working copy cannot be safely published."""


def project_loader_target(project: Path) -> str:
    """Read the package-owned loader target, with the generic export as default."""

    try:
        document = cast(
            dict[str, object],
            tomllib.loads((project / "pyproject.toml").read_text("utf-8")),
        )
        tool = document.get("tool", {})
        if not isinstance(tool, dict):
            raise PluginPublishingError("pyproject.toml [tool] must be a table")
        tool = cast(dict[str, object], tool)
        grafy = tool.get("grafy", {})
        if not isinstance(grafy, dict):
            raise PluginPublishingError("pyproject.toml [tool.grafy] must be a table")
        grafy = cast(dict[str, object], grafy)
        plugin = grafy.get("plugin", {})
        if not isinstance(plugin, dict):
            raise PluginPublishingError(
                "pyproject.toml [tool.grafy.plugin] must be a table"
            )
        plugin = cast(dict[str, object], plugin)
        value = plugin.get("loader-target", WORKSPACE_PLUGIN_LOADER_TARGET)
        if not isinstance(value, str):
            raise PluginPublishingError(
                "pyproject.toml Plugin loader-target must be a string"
            )
        split_plugin_loader_target(value)
        return value
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        if isinstance(exc, PluginPublishingError):
            raise
        raise PluginPublishingError(
            f"Cannot read Plugin loader target from {project / 'pyproject.toml'}"
        ) from exc


@dataclass(frozen=True, slots=True)
class VerifiedPluginCandidate:
    """Immutable source and contract identity produced by verification."""

    catalog: PluginCatalogManifest
    capabilities: PluginCapabilityManifest
    loader_target: str
    source_archive: bytes
    lock_digest: str
    runtime_profile: str

    @property
    def source_digest(self) -> str:
        return sha256(self.source_archive).hexdigest()

    @property
    def contract_digest(self) -> str:
        return plugin_contract_digest(self.catalog)

    @property
    def profile_digest(self) -> str:
        return plugin_profile_digest(self.runtime_profile)


class PluginDirectoryPublisher:
    """Host-compatible verification for a trusted Plugin working copy.

    The working copy is scanned and staged before any Plugin code runs; the
    deterministic source archive and its digest are computed from those staged
    bytes. Tests and inspection consume an unpacked copy of that exact archive
    inside the snapshot's own locked environment, never the mutable working
    directory. The subprocess environment excludes host secrets, but this
    adapter does not isolate the host filesystem or network. System candidates
    must use ``DockerPluginDirectoryPublisher`` from the one-shot publisher.
    """

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        runtime_profile: str,
        wheelhouse: Path | None = None,
    ) -> None:
        self._allowed_roots = tuple(
            root.expanduser().resolve() for root in allowed_roots
        )
        self._runtime_profile = runtime_profile.strip()
        if self._runtime_profile == "":
            raise PluginPublishingError("Plugin runtime profile must not be blank")
        self._wheelhouse = (
            None if wheelhouse is None else wheelhouse.expanduser().resolve()
        )

    def verify(
        self,
        directory: Path,
        *,
        expected_slug: str | None = None,
        loader_target: str | None = None,
    ) -> VerifiedPluginCandidate:
        project = self._require_allowed_project(directory)
        if loader_target is None:
            loader_target = project_loader_target(project)
        entries = scan_source_tree(project)
        staging = Path(tempfile.mkdtemp(prefix="grafy-plugin-publish-"))
        try:
            staged_source = staging / "source"
            for name, content in entries:
                destination = staged_source / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            source_archive = build_deterministic_archive(entries)
            snapshot = staging / "snapshot"
            snapshot.mkdir()
            unpack_source_snapshot(source_archive, snapshot)
            reject_escaping_path_dependencies(snapshot)
            lock_digest = sha256((snapshot / "uv.lock").read_bytes()).hexdigest()
            self._run_uv_command(
                ("uv", "lock", "--check", "--project", str(snapshot)),
                snapshot,
                "lock check",
            )
            self._run_uv_command(
                ("uv", "sync", "--project", str(snapshot), "--locked"),
                snapshot,
                "dependency sync",
            )
            venv_python = snapshot / ".venv" / "bin" / "python"
            constrained_home = staging / "home"
            constrained_home.mkdir()
            environment = constrained_environment(venv_python, constrained_home)
            self._run_constrained_command(
                (str(venv_python), "-m", "pytest", "-q"),
                environment,
                snapshot,
                "tests",
            )
            inspected = self._run_constrained_command(
                (
                    str(venv_python),
                    "-I",
                    "-m",
                    "grafy_core.plugin_inspector",
                    loader_target,
                ),
                environment,
                snapshot,
                "catalog inspection",
            )
            return self._verified_candidate(
                inspection_output=inspected.stdout,
                project=project,
                expected_slug=expected_slug,
                loader_target=loader_target,
                source_archive=source_archive,
                lock_digest=lock_digest,
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _require_allowed_project(self, directory: Path) -> Path:
        try:
            project = directory.expanduser().resolve(strict=True)
        except OSError as exc:
            raise PluginPublishingError(
                f"Plugin project cannot be resolved: {directory}: {exc}"
            ) from exc
        if not project.is_dir():
            raise PluginPublishingError(f"Plugin project is not a directory: {project}")
        if not self._allowed_roots:
            raise PluginPublishingError("No Plugin roots are configured")
        if not any(project.is_relative_to(root) for root in self._allowed_roots):
            rendered = ", ".join(str(root) for root in self._allowed_roots)
            raise PluginPublishingError(
                f"Plugin project {project} is outside configured roots: {rendered}"
            )
        return project

    def _verified_candidate(
        self,
        *,
        inspection_output: str | bytes,
        project: Path,
        expected_slug: str | None,
        loader_target: str,
        source_archive: bytes,
        lock_digest: str,
    ) -> VerifiedPluginCandidate:
        try:
            result = InspectionResult.model_validate_json(inspection_output)
        except ValidationError as exc:
            raise PluginPublishingError(
                "Plugin catalog inspection did not return a valid manifest"
            ) from exc
        if expected_slug is not None and result.catalog.slug != expected_slug:
            raise PluginPublishingError(
                f"Inspected Plugin slug {result.catalog.slug!r} does not match the "
                f"publish target slug {expected_slug!r} for {project}"
            )
        return VerifiedPluginCandidate(
            catalog=result.catalog,
            capabilities=result.capabilities,
            loader_target=loader_target,
            source_archive=source_archive,
            lock_digest=lock_digest,
            runtime_profile=self._runtime_profile,
        )

    def _run_uv_command(
        self,
        command: tuple[str, ...],
        snapshot: Path,
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        if self._wheelhouse is not None:
            existing = environment.get("UV_FIND_LINKS")
            environment["UV_FIND_LINKS"] = (
                f"{existing}{os.pathsep}{self._wheelhouse}"
                if existing
                else str(self._wheelhouse)
            )
        return self._run_subprocess(command, snapshot, operation, environment)

    def _run_constrained_command(
        self,
        command: tuple[str, ...],
        environment: dict[str, str],
        working_directory: Path,
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_subprocess(command, working_directory, operation, environment)

    def _run_subprocess(
        self,
        command: tuple[str, ...],
        working_directory: Path,
        operation: str,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._spawn(command, working_directory, environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PluginPublishingError(f"Plugin {operation} could not run") from exc
        if completed.returncode == 0:
            return completed
        detail = (completed.stderr or completed.stdout).strip()
        if len(detail) > 4_000:
            detail = detail[-4_000:]
        raise PluginPublishingError(
            f"Plugin {operation} failed with exit code {completed.returncode}: {detail}"
        )

    def _spawn(
        self,
        command: tuple[str, ...],
        working_directory: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Run one command through ``posix_spawn`` instead of fork+exec.

        Optional Plugin dependencies (the GIS stack and its PROJ/sqlite
        libraries) register ``pthread_atfork`` handlers. Once they are loaded
        into this process, children spawned by plain fork+exec crash before
        exec on macOS because their handlers call os_log in a state that is
        invalid after fork. ``posix_spawn`` bypasses those handlers.

        CPython only selects its posix_spawn path for an absolute executable,
        no cwd override, and no fd cleanup, so the command runs through a
        shell trampoline that applies the directory; ``exec`` replaces the
        shell so a timeout kill still terminates the real command.
        """
        executable = shutil.which(command[0], path=environment.get("PATH"))
        if executable is None:
            raise FileNotFoundError(
                f"Plugin tool {command[0]!r} is not on the configured PATH"
            )
        trampoline: tuple[str, ...] = (
            "/bin/sh",
            "-c",
            'cd "$1" && shift && exec "$@"',
            "sh",
            str(working_directory),
            executable,
            *command[1:],
        )
        return subprocess.run(
            trampoline,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            close_fds=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )


def scan_source_tree(project: Path) -> list[tuple[str, bytes]]:
    """Validate the working copy and return accepted regular files.

    Symlinks, devices, traversal, escaping paths, and excessive trees are
    rejected with contextual errors before anything is snapshotted. Only
    included paths are accepted; excluded build and cache artifacts are
    skipped.
    """

    entries: list[tuple[str, bytes]] = []
    total_bytes = 0

    def on_walk_error(error: OSError) -> None:
        raise PluginPublishingError(
            f"Plugin source tree cannot be enumerated: {error}"
        ) from error

    for current, directory_names, file_names in os.walk(
        project,
        followlinks=False,
        onerror=on_walk_error,
    ):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            directory_path = current_path / name
            info = directory_path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise PluginPublishingError(
                    f"Plugin project contains unsupported symlinked directory "
                    f"{directory_path} -> {os.readlink(directory_path)}"
                )
            if name not in EXCLUDED_DIRECTORY_NAMES:
                kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(project).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise PluginPublishingError(
                    f"Plugin project contains unsupported symlink "
                    f"{relative!r} -> {os.readlink(path)}"
                )
            if not stat.S_ISREG(info.st_mode):
                raise PluginPublishingError(
                    f"Plugin project contains unsupported special file {relative!r}"
                )
            validate_relative_source_name(relative)
            if not _included_source_path(relative):
                continue
            content = path.read_bytes()
            is_marker = relative == "py.typed" or relative.endswith("/py.typed")
            if (not content and not is_marker) or len(
                content
            ) > MAX_PLUGIN_SOURCE_FILE_BYTES:
                raise PluginPublishingError(
                    f"Plugin source file {relative!r} must contain 1 to "
                    f"{MAX_PLUGIN_SOURCE_FILE_BYTES} bytes"
                )
            total_bytes += len(content)
            if total_bytes > MAX_PLUGIN_SOURCE_BYTES:
                raise PluginPublishingError("Plugin source tree exceeds 64 MiB")
            entries.append((relative, content))
            if len(entries) > MAX_PLUGIN_SOURCE_FILES:
                raise PluginPublishingError(
                    f"Plugin source tree exceeds {MAX_PLUGIN_SOURCE_FILES} files"
                )

    names = {name for name, _ in entries}
    for required in ("pyproject.toml", "uv.lock"):
        if required not in names:
            raise PluginPublishingError(
                f"Plugin source archive is missing {required!r}"
            )
    if not any(name.startswith("src/") for name in names):
        raise PluginPublishingError("Plugin source archive contains no src files")
    if not any(name.startswith("tests/") and name.endswith(".py") for name in names):
        raise PluginPublishingError("Plugin source archive contains no tests")
    return entries


def validate_relative_source_name(relative: str) -> None:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in relative
        or "\x00" in relative
    ):
        raise PluginPublishingError(
            f"Plugin project contains escaping source path {relative!r}"
        )


def build_deterministic_archive(entries: Sequence[tuple[str, bytes]]) -> bytes:
    """Build the canonical gzip tarball from accepted source entries.

    Ordering is the sorted relative path, so the archive bytes do not depend
    on filesystem enumeration order. No generated release metadata is part of
    the archive; release metadata lives beside it in the release descriptor.
    """

    buffer = BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, content in sorted(entries):
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o644
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                archive.addfile(info, BytesIO(content))
    return buffer.getvalue()


def unpack_source_snapshot(source_archive: bytes, destination: Path) -> None:
    """Unpack the frozen archive into a private directory for verification."""

    with tarfile.open(fileobj=BytesIO(source_archive), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                raise PluginPublishingError(
                    f"Plugin source archive contains unsupported entry {member.name!r}"
                )
            validate_relative_source_name(member.name)
        archive.extractall(destination, filter="data")


def source_archive_entries(source_archive: bytes) -> dict[str, bytes]:
    """Read validated regular files from one immutable source archive."""

    entries: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=BytesIO(source_archive), mode="r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    raise PluginPublishingError(
                        "Plugin source archive contains unsupported entry "
                        f"{member.name!r}"
                    )
                validate_relative_source_name(member.name)
                stream = archive.extractfile(member)
                if stream is None:
                    raise PluginPublishingError(
                        f"Plugin source archive entry {member.name!r} is unreadable"
                    )
                entries[member.name] = stream.read()
    except tarfile.TarError as exc:
        raise PluginPublishingError(
            "Plugin source archive is not a readable gzip tarball"
        ) from exc
    return entries


def reject_escaping_path_dependencies(snapshot: Path) -> None:
    """Reject ``[tool.uv.sources]`` path dependencies outside the snapshot."""

    parsed = tomllib.loads((snapshot / "pyproject.toml").read_text(encoding="utf-8"))
    sources = cast(
        dict[str, object],
        parsed.get("tool", {}).get("uv", {}).get("sources", {}),
    )
    for dependency, source in sorted(sources.items()):
        source_table = cast(dict[str, object], source)
        if "path" not in source_table:
            continue
        declared = source_table["path"]
        if not isinstance(declared, str) or PurePosixPath(declared).is_absolute():
            raise PluginPublishingError(
                f"Plugin dependency {dependency!r} declares unsupported path "
                f"source {declared!r}; dependencies must resolve inside the "
                "frozen snapshot"
            )
        resolved = os.path.normpath(snapshot / declared)
        if not Path(resolved).is_relative_to(snapshot):
            raise PluginPublishingError(
                f"Plugin dependency {dependency!r} path source {declared!r} "
                f"resolves to {resolved}, outside the frozen Plugin snapshot "
                f"{snapshot}"
            )


def _included_source_path(value: str) -> bool:
    if value in {"pyproject.toml", "uv.lock", "README.md"}:
        return True
    if value.endswith(".egg-info") or "/.egg-info" in value:
        return False
    if value.startswith("src/"):
        return value.endswith((".py", ".pyi", "py.typed"))
    if value.startswith("wheels/"):
        return value.endswith(".whl")
    return value.startswith("tests/") and value.endswith(".py")


def constrained_environment(venv_python: Path, home: Path) -> dict[str, str]:
    """A secret-free environment for trusted host tests and inspection.

    Only the snapshot's locked interpreter and a private HOME/TMPDIR are
    exposed. Host environment variables — including credentials and secrets —
    are deliberately not inherited. This does not disable filesystem or network
    access; it is not a sandbox.
    """

    return {
        "PATH": os.pathsep.join(
            [str(venv_python.parent), "/usr/local/bin", "/usr/bin", "/bin"]
        ),
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GRAFY_PLUGIN_PUBLISHING": "1",
    }


__all__ = [
    "PluginDirectoryPublisher",
    "constrained_environment",
    "PluginPublishingError",
    "VerifiedPluginCandidate",
    "build_deterministic_archive",
    "reject_escaping_path_dependencies",
    "scan_source_tree",
    "source_archive_entries",
    "unpack_source_snapshot",
]

"""Docker isolation for one-shot and CI Plugin publishers."""

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time

from grafy_api.plugins.publication.source import (
    PluginDirectoryPublisher,
    PluginPublishingError,
    VerifiedPluginCandidate,
    build_deterministic_archive,
    project_loader_target,
    reject_escaping_path_dependencies,
    scan_source_tree,
    unpack_source_snapshot,
)


PUBLISHER_TIMEOUT_SECONDS = 600
PUBLISHER_LOG_LIMIT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PublisherSandboxResult:
    """Bounded output from one publisher sandbox command."""

    returncode: int
    stdout: bytes
    stderr: bytes
    output_truncated: bool


class DockerPublisherSandbox:
    """Run dependency fetch and candidate checks in hardened containers."""

    def __init__(
        self,
        *,
        image: str,
        docker_binary: str = "docker",
        timeout_seconds: int = PUBLISHER_TIMEOUT_SECONDS,
        log_limit_bytes: int = PUBLISHER_LOG_LIMIT_BYTES,
    ) -> None:
        self._image = image.strip()
        self._docker_binary = docker_binary
        self._timeout_seconds = timeout_seconds
        self._log_limit_bytes = log_limit_bytes
        if self._image == "":
            raise PluginPublishingError("Plugin publisher image must not be blank")
        if timeout_seconds < 1:
            raise PluginPublishingError("Plugin publisher timeout must be positive")
        if log_limit_bytes < 1:
            raise PluginPublishingError("Plugin publisher log limit must be positive")

    def run(
        self,
        command: tuple[str, ...],
        *,
        source: Path,
        source_read_only: bool,
        environment_directory: Path,
        cache_directory: Path,
        network_enabled: bool,
        environment_read_only: bool,
        operation: str,
    ) -> PublisherSandboxResult:
        docker_command = self.command(
            command,
            source=source,
            source_read_only=source_read_only,
            environment_directory=environment_directory,
            cache_directory=cache_directory,
            network_enabled=network_enabled,
            environment_read_only=environment_read_only,
        )
        try:
            result = self._spawn(docker_command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PluginPublishingError(
                f"Plugin publisher sandbox {operation} could not run"
            ) from exc
        if result.output_truncated:
            raise PluginPublishingError(
                f"Plugin publisher sandbox {operation} exceeded the "
                f"{self._log_limit_bytes}-byte output limit"
            )
        if result.returncode == 0:
            return result
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")
        raise PluginPublishingError(
            f"Plugin publisher sandbox {operation} failed with exit code "
            f"{result.returncode}: {detail.strip()}"
        )

    def command(
        self,
        candidate_command: tuple[str, ...],
        *,
        source: Path,
        source_read_only: bool,
        environment_directory: Path,
        cache_directory: Path,
        network_enabled: bool,
        environment_read_only: bool,
    ) -> tuple[str, ...]:
        """Build the complete auditable Docker invocation for one phase."""

        source_mount = f"type=bind,src={source},dst=/candidate"
        if source_read_only:
            source_mount += ",readonly"
        environment_mount = (
            f"type=bind,src={environment_directory},dst=/venv,readonly"
            if environment_read_only
            else f"type=bind,src={environment_directory},dst=/venv"
        )
        cache_mount = (
            f"type=bind,src={cache_directory},dst=/cache,readonly"
            if environment_read_only
            else f"type=bind,src={cache_directory},dst=/cache"
        )
        return (
            self._docker_binary,
            "run",
            "--rm",
            "--init",
            "--network",
            "bridge" if network_enabled else "none",
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "1g",
            "--memory-swap",
            "1g",
            "--cpus",
            "1.0",
            "--log-driver",
            "none",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--mount",
            source_mount,
            "--mount",
            environment_mount,
            "--mount",
            cache_mount,
            "--workdir",
            "/candidate",
            "--env",
            "HOME=/tmp",
            "--env",
            "TMPDIR=/tmp",
            "--env",
            "LANG=C.UTF-8",
            "--env",
            "PYTHONHASHSEED=0",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "GRAFY_PLUGIN_PUBLISHING=1",
            "--env",
            "UV_CACHE_DIR=/cache",
            "--env",
            "VIRTUAL_ENV=/venv",
            self._image,
            *candidate_command,
        )

    def _spawn(self, command: tuple[str, ...]) -> PublisherSandboxResult:
        executable = shutil.which(command[0])
        if executable is None:
            raise FileNotFoundError(
                f"Plugin publisher tool {command[0]!r} is not on PATH"
            )
        started_at = time.monotonic()
        process = subprocess.Popen(
            (executable, *command[1:]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise PluginPublishingError("Plugin publisher output pipes are unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        output = {"stdout": bytearray(), "stderr": bytearray()}
        total_bytes = 0
        truncated = False
        try:
            while selector.get_map():
                remaining = self._timeout_seconds - (time.monotonic() - started_at)
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    raise subprocess.TimeoutExpired(command, self._timeout_seconds)
                for key, _ in selector.select(timeout=min(remaining, 1.0)):
                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > self._log_limit_bytes:
                        truncated = True
                    remaining_capacity = self._log_limit_bytes - sum(
                        len(value) for value in output.values()
                    )
                    if remaining_capacity > 0:
                        output[key.data].extend(chunk[:remaining_capacity])
            returncode = process.wait()
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait()
        return PublisherSandboxResult(
            returncode=returncode,
            stdout=bytes(output["stdout"]),
            stderr=bytes(output["stderr"]),
            output_truncated=truncated,
        )


class DockerPluginDirectoryPublisher(PluginDirectoryPublisher):
    """Freeze locally, then verify exclusively inside Docker sandboxes."""

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        runtime_profile: str,
        image: str,
        docker_binary: str = "docker",
        scratch_root: Path | None = None,
    ) -> None:
        super().__init__(allowed_roots, runtime_profile=runtime_profile)
        self._sandbox = DockerPublisherSandbox(
            image=image,
            docker_binary=docker_binary,
        )
        self._scratch_root = (
            None if scratch_root is None else scratch_root.expanduser().resolve()
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
        source_archive = build_deterministic_archive(entries)
        if self._scratch_root is not None:
            self._scratch_root.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix="grafy-plugin-publisher-",
                dir=self._scratch_root,
            )
        )
        try:
            snapshot = staging / "snapshot"
            build_snapshot = staging / "build-snapshot"
            environment_directory = staging / "venv"
            cache_directory = staging / "cache"
            snapshot.mkdir()
            environment_directory.mkdir()
            cache_directory.mkdir()
            unpack_source_snapshot(source_archive, snapshot)
            reject_escaping_path_dependencies(snapshot)
            shutil.copytree(snapshot, build_snapshot)
            lock_digest = sha256((snapshot / "uv.lock").read_bytes()).hexdigest()
            self._sandbox.run(
                ("uv", "lock", "--check", "--project", "/candidate"),
                source=snapshot,
                source_read_only=True,
                environment_directory=environment_directory,
                cache_directory=cache_directory,
                network_enabled=True,
                environment_read_only=False,
                operation="lock check",
            )
            self._sandbox.run(
                (
                    "uv",
                    "sync",
                    "--project",
                    "/candidate",
                    "--locked",
                    "--active",
                    "--no-editable",
                    "--find-links",
                    "/candidate/wheels",
                ),
                source=build_snapshot,
                source_read_only=False,
                environment_directory=environment_directory,
                cache_directory=cache_directory,
                network_enabled=True,
                environment_read_only=False,
                operation="dependency fetch",
            )
            self._sandbox.run(
                ("/venv/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider"),
                source=snapshot,
                source_read_only=True,
                environment_directory=environment_directory,
                cache_directory=cache_directory,
                network_enabled=False,
                environment_read_only=True,
                operation="tests",
            )
            inspected = self._sandbox.run(
                (
                    "/venv/bin/python",
                    "-I",
                    "-m",
                    "grafy_core.plugin_inspector",
                    loader_target,
                ),
                source=snapshot,
                source_read_only=True,
                environment_directory=environment_directory,
                cache_directory=cache_directory,
                network_enabled=False,
                environment_read_only=True,
                operation="catalog inspection",
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


__all__ = [
    "DockerPluginDirectoryPublisher",
    "DockerPublisherSandbox",
    "PublisherSandboxResult",
]

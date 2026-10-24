import argparse
import os
import resource
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class BoundedSubprocessResourceLimits:
    address_space_bytes: int
    cpu_seconds: int
    open_files: int
    file_size_bytes: int


@dataclass(frozen=True, slots=True)
class BoundedSubprocessPolicy:
    address_space_bytes: int
    cpu_seconds: int
    open_files: int
    wall_time_seconds: float
    stdout_limit_bytes: int
    stderr_limit_bytes: int
    file_size_bytes: int


DEFAULT_POLICY = BoundedSubprocessPolicy(
    address_space_bytes=16 * 1_024 * 1_024 * 1_024,
    cpu_seconds=3_600,
    open_files=256,
    wall_time_seconds=3_600.0,
    stdout_limit_bytes=1 * 1_024 * 1_024,
    stderr_limit_bytes=1 * 1_024 * 1_024,
    file_size_bytes=100 * 1_024 * 1_024 * 1_024,
)
# One process-wide cap shared by every run() caller.
_MAX_CONCURRENT_PROCESSES = 4
_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT_PROCESSES)
_DIAGNOSTIC_LIMIT = 1_000
_RESERVED_ENVIRONMENT_PREFIX = "GRAFY_BOUNDED_"


class BoundedSubprocessError(RuntimeError):
    def __init__(
        self,
        operation: str,
        returncode: int | None,
        timed_out: bool,
        diagnostic: str,
        *,
        diagnostic_truncated: bool = False,
    ) -> None:
        self.operation = operation
        self.returncode = returncode
        self.timed_out = timed_out
        self.diagnostic = _compact(diagnostic, truncated=diagnostic_truncated)
        status = "timed out" if timed_out else f"exited with code {returncode}"
        super().__init__(f"{operation} {status}: {self.diagnostic}")


@dataclass(slots=True)
class _CapturedStream:
    limit_bytes: int
    value: bytearray = field(default_factory=bytearray)
    truncated: bool = False


def _compact(value: str, *, truncated: bool = False) -> str:
    compact = " ".join(value.split())
    marker = " [truncated]" if truncated else ""
    if compact == "":
        return "output truncated" if truncated else "no diagnostic output"
    available = _DIAGNOSTIC_LIMIT - len(marker)
    if len(compact) > available:
        compact = f"{compact[: available - 3]}..."
    return f"{compact}{marker}"


def _set_limit(limit: int, soft: int, hard: int) -> None:
    _current_soft, current_hard = resource.getrlimit(limit)
    effective_hard = hard
    if current_hard != resource.RLIM_INFINITY:
        effective_hard = min(effective_hard, current_hard)
    resource.setrlimit(limit, (min(soft, effective_hard), effective_hard))


def _apply_resource_limits(limits: BoundedSubprocessResourceLimits) -> None:
    _set_limit(resource.RLIMIT_CORE, 0, 0)
    _set_limit(resource.RLIMIT_CPU, limits.cpu_seconds, limits.cpu_seconds + 1)
    _set_limit(resource.RLIMIT_FSIZE, limits.file_size_bytes, limits.file_size_bytes)
    _set_limit(resource.RLIMIT_NOFILE, limits.open_files, limits.open_files)
    if sys.platform != "darwin" and hasattr(resource, "RLIMIT_AS"):
        _set_limit(
            resource.RLIMIT_AS,
            limits.address_space_bytes,
            limits.address_space_bytes,
        )


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _parse_launcher_arguments(
    argv: Sequence[str],
) -> tuple[BoundedSubprocessResourceLimits, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--address-space", type=_positive_integer, required=True)
    parser.add_argument("--cpu-seconds", type=_positive_integer, required=True)
    parser.add_argument("--open-files", type=_positive_integer, required=True)
    parser.add_argument("--file-size", type=_positive_integer, required=True)
    try:
        separator = argv.index("--")
    except ValueError:
        parser.error("missing -- before the child command")
    options = parser.parse_args(argv[:separator])
    command = list(argv[separator + 1 :])
    if not command:
        parser.error("missing child command after --")
    limits = BoundedSubprocessResourceLimits(
        address_space_bytes=options.address_space,
        cpu_seconds=options.cpu_seconds,
        open_files=options.open_files,
        file_size_bytes=options.file_size,
    )
    return limits, command


def main(argv: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    limits, command = _parse_launcher_arguments(arguments)
    _apply_resource_limits(limits)
    try:
        os.execvpe(command[0], command, os.environ)
    except OSError as exc:
        print(f"{command[0]}: {exc}", file=sys.stderr)
        return 127


def _read_bounded(stream: BinaryIO, capture: _CapturedStream) -> None:
    while True:
        chunk = stream.read(64 * 1_024)
        if not chunk:
            break
        remaining = capture.limit_bytes - len(capture.value)
        captured = min(len(chunk), max(remaining, 0))
        capture.value.extend(chunk[:captured])
        if captured < len(chunk):
            capture.truncated = True


def _decode(value: bytearray) -> str:
    return bytes(value).decode("utf-8", errors="replace")


def _diagnostic(stderr: _CapturedStream, stdout: _CapturedStream) -> tuple[str, bool]:
    if stderr.value or stderr.truncated:
        return _decode(stderr.value), stderr.truncated
    return _decode(stdout.value), stdout.truncated


def run(
    argv: Sequence[str],
    *,
    operation: str,
    env: Mapping[str, str],
    cwd: Path | str | None = None,
    stdin: str | None = None,
    policy: BoundedSubprocessPolicy = DEFAULT_POLICY,
) -> subprocess.CompletedProcess[str]:
    if not argv:
        raise ValueError("argv must not be empty")
    resource_values = (
        policy.address_space_bytes,
        policy.cpu_seconds,
        policy.open_files,
        policy.file_size_bytes,
    )
    if any(value <= 0 for value in resource_values):
        raise ValueError("subprocess resource limits must be positive")
    if (
        policy.wall_time_seconds <= 0
        or policy.stdout_limit_bytes < 0
        or policy.stderr_limit_bytes < 0
    ):
        raise ValueError("subprocess output and wall-clock limits are invalid")

    command = [
        sys.executable,
        "-m",
        "grafy_core.bounded_subprocess",
        f"--address-space={policy.address_space_bytes}",
        f"--cpu-seconds={policy.cpu_seconds}",
        f"--open-files={policy.open_files}",
        f"--file-size={policy.file_size_bytes}",
        "--",
        *argv,
    ]
    process_env = {
        key: value
        for key, value in env.items()
        if not key.startswith(_RESERVED_ENVIRONMENT_PREFIX)
    }
    stdout = _CapturedStream(policy.stdout_limit_bytes)
    stderr = _CapturedStream(policy.stderr_limit_bytes)
    process: subprocess.Popen[bytes] | None = None
    try:
        with _SEMAPHORE:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                cwd=cwd,
                env=process_env,
                close_fds=True,
                start_new_session=True,
            )
            stdout_pipe = process.stdout
            stderr_pipe = process.stderr
            if stdout_pipe is None or stderr_pipe is None:
                _kill_group(process)
                returncode = process.wait()
                raise BoundedSubprocessError(
                    operation,
                    returncode,
                    False,
                    "subprocess output pipes were unavailable",
                )

            stdout_reader = threading.Thread(
                target=_read_bounded,
                args=(stdout_pipe, stdout),
                daemon=True,
            )
            stderr_reader = threading.Thread(
                target=_read_bounded,
                args=(stderr_pipe, stderr),
                daemon=True,
            )
            stdout_reader.start()
            stderr_reader.start()

            writer: threading.Thread | None = None
            if stdin is not None:
                stdin_pipe = process.stdin
                if stdin_pipe is None:
                    _kill_group(process)
                    returncode = process.wait()
                    stdout_reader.join()
                    stderr_reader.join()
                    raise BoundedSubprocessError(
                        operation,
                        returncode,
                        False,
                        "subprocess input pipe was unavailable",
                    )
                writer = threading.Thread(
                    target=_write_stdin,
                    args=(stdin_pipe, stdin.encode("utf-8")),
                    daemon=True,
                )
                writer.start()

            try:
                returncode = process.wait(timeout=policy.wall_time_seconds)
            except subprocess.TimeoutExpired:
                _kill_group(process)
                returncode = process.wait()
                if writer is not None:
                    writer.join()
                stdout_reader.join()
                stderr_reader.join()
                diagnostic, truncated = _diagnostic(stderr, stdout)
                raise BoundedSubprocessError(
                    operation,
                    returncode,
                    True,
                    diagnostic,
                    diagnostic_truncated=truncated,
                )
            if writer is not None:
                writer.join()
            stdout_reader.join()
            stderr_reader.join()
    except BoundedSubprocessError:
        raise
    except OSError as exc:
        raise BoundedSubprocessError(operation, None, False, str(exc)) from exc

    result = subprocess.CompletedProcess(
        list(argv), returncode, _decode(stdout.value), _decode(stderr.value)
    )
    if returncode != 0:
        diagnostic, truncated = _diagnostic(stderr, stdout)
        raise BoundedSubprocessError(
            operation,
            returncode,
            False,
            diagnostic,
            diagnostic_truncated=truncated,
        )
    return result


def _write_stdin(stream: BinaryIO, value: bytes) -> None:
    try:
        stream.write(value)
    except OSError:
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


if __name__ == "__main__":
    sys.exit(main())

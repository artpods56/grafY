import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

import pytest
import grafy_core.bounded_subprocess as bounded
from grafy_core.bounded_subprocess import (
    BoundedSubprocessError,
    BoundedSubprocessPolicy,
    run,
)


def policy(**overrides: object) -> BoundedSubprocessPolicy:
    values: dict[str, int | float] = {
        "address_space_bytes": 16 * 1_024 * 1_024 * 1_024,
        "cpu_seconds": 30,
        "open_files": 64,
        "wall_time_seconds": 10.0,
        "stdout_limit_bytes": 2_000,
        "stderr_limit_bytes": 2_000,
        "file_size_bytes": 1_024 * 1_024,
    }
    values.update(overrides)  # type: ignore[arg-type]
    return BoundedSubprocessPolicy(**values)


def child_env() -> dict[str, str]:
    return {"PATH": os.defpath, "LANG": "C.UTF-8"}


def test_run_returns_captured_stdout() -> None:
    result = run(
        [sys.executable, "-c", "print('bounded output')"],
        operation="capture output",
        env=child_env(),
    )

    assert result.stdout == "bounded output\n"
    assert result.stderr == ""


def test_nonzero_exit_has_operation_and_bounded_diagnostic() -> None:
    with pytest.raises(BoundedSubprocessError) as raised:
        run(
            [sys.executable, "-c", "import sys; print('  bad\\n output  '); sys.exit(7)"],
            operation="convert raster",
            env=child_env(),
            policy=policy(stderr_limit_bytes=8_000),
        )

    assert raised.value.operation == "convert raster"
    assert raised.value.returncode == 7
    assert raised.value.diagnostic == "bad output"

    with pytest.raises(BoundedSubprocessError) as oversized:
        run(
            [
                sys.executable,
                "-c",
                "import sys; print('x' * 500, file=sys.stderr); sys.exit(2)",
            ],
            operation="bounded diagnostics",
            env=child_env(),
            policy=policy(stderr_limit_bytes=32),
        )
    assert oversized.value.diagnostic == f"{'x' * 32} [truncated]"


def test_stdout_and_stderr_have_independent_capture_limits() -> None:
    result = run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('abcdef'); sys.stderr.write('123456')",
        ],
        operation="capture bounded streams",
        env=child_env(),
        policy=policy(stdout_limit_bytes=3, stderr_limit_bytes=5),
    )

    assert result.stdout == "abc"
    assert result.stderr == "12345"


def test_launcher_parses_resource_limits_from_argv() -> None:
    limits, command = bounded._parse_launcher_arguments(
        [
            "--address-space=1024",
            "--cpu-seconds=30",
            "--open-files=64",
            "--file-size=4096",
            "--",
            "gdalinfo",
            "--version",
        ]
    )

    assert limits == bounded.BoundedSubprocessResourceLimits(
        address_space_bytes=1024,
        cpu_seconds=30,
        open_files=64,
        file_size_bytes=4096,
    )
    assert command == ["gdalinfo", "--version"]


def test_timeout_kills_process_group_including_grandchildren() -> None:
    command = (
        "import subprocess, sys, signal; "
        "subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()']); "
        "signal.pause()"
    )
    with pytest.raises(BoundedSubprocessError) as raised:
        run(
            [sys.executable, "-c", command],
            operation="stuck tiling",
            env=child_env(),
            policy=policy(wall_time_seconds=0.5),
        )

    assert raised.value.timed_out is True
    assert raised.value.operation == "stuck tiling"


@pytest.mark.skipif(sys.platform == "darwin", reason="RLIMIT_AS is unreliable on macOS")
def test_child_cannot_allocate_past_address_space_cap() -> None:
    cap = 256 * 1_024 * 1_024
    result = run(
        [
            sys.executable,
            "-c",
            "try:\n bytearray(384 * 1024 * 1024)\n print('allocated')\n"
            "except MemoryError:\n print('limited')",
        ],
        operation="check address-space limit",
        env=child_env(),
        policy=policy(address_space_bytes=cap),
    )

    assert result.stdout.strip() == "limited"


def test_explicit_environment_is_the_only_environment_passed_to_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_TEST_SECRET_SENTINEL", "secret-value")
    monkeypatch.setenv("LANG", "allowlisted-locale")
    result = run(
        [
            sys.executable,
            "-c",
            "import os; print(os.getenv('GRAFY_TEST_SECRET_SENTINEL', 'missing')); "
            "print(os.getenv('LANG', 'missing')); "
            "print(os.getenv('GRAFY_BOUNDED_AS', 'missing'))",
        ],
        operation="inspect environment",
        env={
            "PATH": os.defpath,
            "LANG": os.environ["LANG"],
            "GRAFY_BOUNDED_AS": "must-not-reach-grandchild",
        },
    )

    assert result.stdout.splitlines() == [
        "missing",
        "allowlisted-locale",
        "missing",
    ]


def test_semaphore_caps_concurrent_children(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = 2
    monkeypatch.setattr(bounded, "_SEMAPHORE", BoundedSemaphore(cap))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    command = (
        "import socket, sys; "
        f"s=socket.create_connection(({host!r}, {port})); "
        "s.sendall(b'+'); s.recv(1); s.close()"
    )

    def job() -> subprocess.CompletedProcess[str]:
        return run(
            [sys.executable, "-c", command],
            operation="concurrency probe",
            env=child_env(),
            policy=policy(),
        )

    peak = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = [executor.submit(job) for _ in range(4)]
        for _ in range(0, 4, cap):
            active: list[socket.socket] = []
            for _ in range(cap):
                connection, _address = listener.accept()
                assert connection.recv(1) == b"+"
                active.append(connection)
            peak = max(peak, len(active))
            for connection in active:
                connection.sendall(b"x")
                connection.close()
        assert [job.result().returncode for job in jobs] == [0, 0, 0, 0]
    listener.close()

    assert peak == cap


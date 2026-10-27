import asyncio
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import BoundedSemaphore, Event

import pytest
import grafy_core.bounded_subprocess as bounded
from grafy_core.bounded_subprocess import (
    BoundedSubprocessError,
    BoundedSubprocessPolicy,
    run,
    run_in_thread,
)


def policy(**overrides: int | float) -> BoundedSubprocessPolicy:
    base = replace(
        bounded.DEFAULT_POLICY,
        cpu_seconds=30,
        wall_time_seconds=10.0,
        stdout_limit_bytes=2_000,
        stderr_limit_bytes=2_000,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


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
            [
                sys.executable,
                "-c",
                "import sys; print('  bad\\n output  '); sys.exit(7)",
            ],
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


def test_successful_parent_cannot_leave_descendants_holding_output_pipes() -> None:
    result = run(
        [
            sys.executable,
            "-c",
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()']); "
            "print('parent complete')",
        ],
        operation="descendant pipe cleanup",
        env=child_env(),
        policy=policy(),
    )
    assert result.stdout == "parent complete\n"


def test_crashed_native_process_does_not_break_next_invocation() -> None:
    with pytest.raises(BoundedSubprocessError) as raised:
        run(
            [
                sys.executable,
                "-c",
                "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)",
            ],
            operation="native crash",
            env=child_env(),
        )
    assert raised.value.returncode == -11
    result = run(
        [sys.executable, "-c", "print('alive')"],
        operation="after crash",
        env=child_env(),
    )
    assert result.stdout == "alive\n"


def test_child_receives_cpu_file_descriptor_and_file_size_limits() -> None:
    result = run(
        [
            sys.executable,
            "-c",
            "import json, resource; "
            "print(json.dumps([resource.getrlimit(k) for k in "
            "(resource.RLIMIT_CPU, resource.RLIMIT_NOFILE, resource.RLIMIT_FSIZE, resource.RLIMIT_CORE)]))",
        ],
        operation="inspect limits",
        env=child_env(),
        policy=policy(open_files=64, file_size_bytes=4096),
    )
    assert json.loads(result.stdout) == [[30, 31], [64, 64], [4096, 4096], [0, 0]]


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS CPU rlimits differ")
def test_cpu_bound_native_child_is_terminated() -> None:
    with pytest.raises(BoundedSubprocessError) as raised:
        run(
            [sys.executable, "-c", "while True: pass"],
            operation="cpu hog",
            env=child_env(),
            policy=policy(cpu_seconds=1),
        )
    assert raised.value.returncode in {-24, -9}
    assert not raised.value.timed_out


@pytest.mark.asyncio
async def test_cancellation_waits_for_process_exit_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = BoundedSemaphore(1)
    monkeypatch.setattr(bounded, "_SEMAPHORE", gate)
    accepted: asyncio.Queue[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.Queue()
    )

    async def connected(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await accepted.put((reader, writer))

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        command = (
            "import socket, os; "
            f"s=socket.create_connection(('127.0.0.1', {port})); "
            "s.sendall((str(os.getpid()) + '\\n').encode()); s.recv(1)"
        )
        work = asyncio.create_task(
            run_in_thread(
                run,
                [sys.executable, "-c", command],
                operation="cancel running child",
                env=child_env(),
                policy=policy(),
            )
        )
        reader, writer = await asyncio.wait_for(accepted.get(), timeout=5)
        try:
            pid = int(await asyncio.wait_for(reader.readline(), timeout=5))
            work.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(work, timeout=5)
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            assert await asyncio.wait_for(reader.read(), timeout=5) == b""
            assert gate.acquire(blocking=False)
            gate.release()
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_capacity_never_spawns_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = BoundedSemaphore(1)
    gate.acquire()
    monkeypatch.setattr(bounded, "_SEMAPHORE", gate)
    entered = Event()
    loop = asyncio.get_running_loop()
    waiting = asyncio.Event()
    marker = tmp_path / "unexpected-child"

    def operation() -> None:
        entered.set()
        loop.call_soon_threadsafe(waiting.set)
        run(
            [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            ],
            operation="queued child",
            env=child_env(),
        )

    work = asyncio.create_task(run_in_thread(operation))
    await asyncio.wait_for(waiting.wait(), timeout=5)
    assert entered.is_set()
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(work, timeout=5)
    assert not gate.acquire(blocking=False)
    gate.release()
    assert not marker.exists()

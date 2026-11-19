import asyncio
import signal
import sys
from unittest.mock import Mock

import pytest

from scripts import dev_stack


WEB = dev_stack.Service("web", ("just", "web", "3000"), 3000, "/")
API = dev_stack.Service("api", ("just", "api"), 8000, "/ready")
TILER = dev_stack.Service("tiler", ("just", "tiler"), 8100, "/health")
KEYCLOAK = dev_stack.Service("keycloak", ("just", "keycloak-up"), 8081, "/health/ready")
APPS = (WEB, API, TILER)


async def test_occupied_port_prevents_all_launches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def port_in_use(port: int) -> bool:
        return port == 8000

    monkeypatch.setattr(dev_stack, "port_in_use", port_in_use)
    start = Mock()
    monkeypatch.setattr(dev_stack, "start", start)

    assert await dev_stack.supervise(APPS, KEYCLOAK, asyncio.Event()) == 1
    start.assert_not_called()
    assert capsys.readouterr().err == "[dev] http://localhost:8000 is already in use\n"


@pytest.mark.parametrize("keycloak_ready", [True, False])
async def test_starts_apps_and_reports_urls_after_health_checks(
    keycloak_ready: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stopping = asyncio.Event()
    launched: list[dev_stack.Service] = []
    stopped: list[dev_stack.Service] = []

    async def start(service: dev_stack.Service) -> dev_stack.Child:
        launched.append(service)
        returncode = 0 if service == KEYCLOAK else None
        return dev_stack.Child(service, Mock(returncode=returncode), Mock())

    async def shutdown(children: list[dev_stack.Child]) -> None:
        stopped.extend(child.service for child in children)

    calls = 0

    async def poll(stopping: asyncio.Event) -> None:
        nonlocal calls
        if calls == 0:
            assert "Grafy is ready" not in capsys.readouterr().out
        else:
            stopping.set()
        calls += 1

    def healthy(service: dev_stack.Service) -> bool:
        if service == KEYCLOAK:
            return keycloak_ready
        assert tuple(launched[-3:]) == APPS
        return calls > 0 or service != TILER

    monkeypatch.setattr(dev_stack, "start", start)
    monkeypatch.setattr(dev_stack, "shutdown", shutdown)
    monkeypatch.setattr(dev_stack, "port_in_use", Mock(return_value=False))
    monkeypatch.setattr(dev_stack, "healthy", healthy)
    monkeypatch.setattr(dev_stack, "poll_until_stopped", poll)

    assert await dev_stack.supervise(APPS, KEYCLOAK, stopping) == 0
    expected = list(APPS) if keycloak_ready else [KEYCLOAK, *APPS]
    assert launched == stopped == expected
    assert capsys.readouterr().out == (
        "Grafy is ready\n"
        "  web  http://localhost:3000\n"
        "  api  http://localhost:8000\n"
        "  tiler  http://localhost:8100\n"
    )


@pytest.mark.parametrize("failed_service", [KEYCLOAK, API])
async def test_child_failure_cleans_up_launched_services(
    failed_service: dev_stack.Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stopped: list[dev_stack.Service] = []

    async def start(service: dev_stack.Service) -> dev_stack.Child:
        returncode = 12 if service == failed_service else None
        return dev_stack.Child(service, Mock(returncode=returncode), Mock())

    async def shutdown(children: list[dev_stack.Child]) -> None:
        stopped.extend(child.service for child in children)

    monkeypatch.setattr(dev_stack, "start", start)
    monkeypatch.setattr(dev_stack, "shutdown", shutdown)
    monkeypatch.setattr(dev_stack, "port_in_use", Mock(return_value=False))
    monkeypatch.setattr(dev_stack, "healthy", Mock(return_value=failed_service == API))

    assert await dev_stack.supervise(APPS, KEYCLOAK, asyncio.Event()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "exited with status 12" in captured.err
    assert stopped == ([KEYCLOAK] if failed_service == KEYCLOAK else list(APPS))


async def test_shutdown_signals_grandchild_and_drains_its_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    grandchild = """
import signal

def stop(signum, frame):
    print("grandchild got SIGTERM")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
print("grandchild ready")
while True:
    signal.pause()
"""
    parent = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {grandchild!r}])"
    service = dev_stack.Service("test", (sys.executable, "-c", parent), 0, "")
    ready = asyncio.Event()
    real_print = print

    def observe_logs(message: str, *, flush: bool) -> None:
        real_print(message, flush=flush)
        if message == "[test] grandchild ready":
            ready.set()

    monkeypatch.setattr(dev_stack, "print", observe_logs, raising=False)
    child = await dev_stack.start(service)
    try:
        await ready.wait()
    finally:
        await dev_stack.shutdown([child])

    assert child.process.returncode == -signal.SIGTERM
    assert capsys.readouterr().out.splitlines() == [
        "[test] grandchild ready",
        "[test] grandchild got SIGTERM",
    ]


async def test_oversized_log_line_reaches_the_reader_without_stalling_the_writer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One line past the stream reader's own limit used to take the stack down.

    `async for line in stream` raises once a line is longer than the reader's
    64 KiB limit. The log task died with the pipe undrained, so the service then
    blocked on its next write and the supervised run hung with no output: `next
    dev` quotes the module it failed on, and uvicorn logs a long request. A
    progress bar that redraws with carriage breaks never sends a newline at all,
    which is the second shape asserted here.
    """
    # The child builds these itself: an expanded 256 KiB literal in one `-c`
    # argument is over Linux's MAX_ARG_STRLEN, so the spawn would fail on a runner
    # where the same test passes on a laptop.
    size = dev_stack.LOG_CHUNK * 2
    long_line = "x" * size
    progress = "P" * size
    service = dev_stack.Service(
        "test",
        (
            sys.executable,
            "-c",
            f"import sys; w = sys.stdout.write; "
            f"w('x' * {size} + '\\n'); w('P' * {size}); w('done\\n'); "
            "sys.stdout.flush()",
        ),
        0,
        "",
    )

    child = await dev_stack.start(service)
    # The writer stops mid-buffer until the reader keeps draining, so a reader
    # that died surfaces here as a timeout rather than as a silently short run.
    await asyncio.wait_for(child.process.wait(), 10)
    await asyncio.wait_for(child.logs, 10)

    # Chunk boundaries fall wherever the pipe happens to fill, so only the
    # concatenation is fixed: nothing dropped, nothing reordered, nothing eaten.
    printed = capsys.readouterr().out.splitlines()
    assert child.process.returncode == 0
    assert "".join(line.removeprefix("[test] ") for line in printed) == (
        long_line + progress + "done"
    )


async def test_shutdown_escalates_for_captured_group_after_leader_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock(spec=asyncio.subprocess.Process, pid=4321, returncode=0)

    async def done() -> None:
        pass

    child = dev_stack.Child(WEB, process, asyncio.create_task(done()))
    killpg = Mock()
    monkeypatch.setattr(dev_stack.os, "killpg", killpg)
    monkeypatch.setattr(dev_stack, "SHUTDOWN_GRACE", 0)

    await dev_stack.shutdown([child])

    assert [call.args for call in killpg.call_args_list] == [
        (4321, signal.SIGTERM),
        (4321, 0),
        (4321, signal.SIGKILL),
    ]
    process.wait.assert_awaited_once()

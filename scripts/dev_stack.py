"""Run the native development services in their own process groups."""

import asyncio
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
import os
import signal
import socket
import sys


STARTUP_TIMEOUT = 180
SHUTDOWN_GRACE = 5
POLL_INTERVAL = 0.2
# The size of one read from a service's output. A StreamReader only guarantees a
# line up to its own 64 KiB limit, so the lines are reassembled here.
LOG_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Service:
    name: str
    command: tuple[str, ...]
    port: int
    health_path: str

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"


@dataclass(frozen=True)
class Child:
    service: Service
    process: asyncio.subprocess.Process
    logs: asyncio.Task[None]


class StartupError(RuntimeError):
    pass


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


def healthy(service: Service) -> bool:
    connection = HTTPConnection("localhost", service.port, timeout=0.5)
    try:
        connection.request("GET", service.health_path)
        return 200 <= connection.getresponse().status < 300
    except (OSError, HTTPException):
        return False
    finally:
        connection.close()


def print_line(name: str, chunk: bytes) -> None:
    print(f"[{name}] {chunk.decode(errors='replace').rstrip()}", flush=True)


async def print_logs(name: str, stream: asyncio.StreamReader) -> None:
    """Echo one service's output, keeping the pipe drained at every size.

    Lines are reassembled from chunks rather than read with `async for line in
    stream`: past the reader's 64 KiB line limit that iteration raises, this task
    dies with the pipe undrained, and the service blocks forever on its next
    write. A line that big is ordinary development output — `next dev` quotes the
    module it failed on, uvicorn logs a long request — so it must not take the
    stack down with it.
    """
    pending = b""
    while chunk := await stream.read(LOG_CHUNK):
        *lines, pending = (pending + chunk).split(b"\n")
        for line in lines:
            print_line(name, line)
        if len(pending) > LOG_CHUNK:
            # No newline in a whole buffer: a progress bar redrawing with `\r`.
            # Print it and restart the line, so bytes keep flowing in both
            # directions however the service chooses to break its output.
            print_line(name, pending)
            pending = b""
    if pending:
        print_line(name, pending)


async def start(service: Service) -> Child:
    process = await asyncio.create_subprocess_exec(
        *service.command,
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert process.stdout is not None
    logs = asyncio.create_task(print_logs(service.name, process.stdout))
    return Child(service, process, logs)


def signal_group(child: Child, sig: int) -> bool:
    try:
        os.killpg(child.process.pid, sig)
    except ProcessLookupError:
        return False
    return True


async def shutdown(children: list[Child]) -> None:
    for child in children:
        signal_group(child, signal.SIGTERM)

    deadline = asyncio.get_running_loop().time() + SHUTDOWN_GRACE
    while any(signal_group(child, 0) for child in children):
        if asyncio.get_running_loop().time() >= deadline:
            for child in children:
                signal_group(child, signal.SIGKILL)
            break
        await asyncio.sleep(POLL_INTERVAL)

    await asyncio.gather(*(child.process.wait() for child in children))
    await asyncio.gather(*(child.logs for child in children))


async def poll_until_stopped(stopping: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stopping.wait(), timeout=POLL_INTERVAL)
    except TimeoutError:
        pass


async def ensure_keycloak(
    service: Service, children: list[Child], stopping: asyncio.Event
) -> None:
    if await asyncio.to_thread(healthy, service) or stopping.is_set():
        return
    child = await start(service)
    children.append(child)
    deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT
    while not stopping.is_set():
        if child.process.returncode == 0:
            return  # keycloak-up uses Compose's --wait health check.
        if child.process.returncode is not None:
            raise StartupError(
                f"keycloak-up exited with status {child.process.returncode}"
            )
        if asyncio.get_running_loop().time() >= deadline:
            raise StartupError("Timed out waiting for keycloak-up")
        await poll_until_stopped(stopping)


def check_running(children: list[Child]) -> None:
    for child in children:
        if child.process.returncode is not None:
            raise StartupError(
                f"{child.service.name} exited with status {child.process.returncode}"
            )


async def supervise(
    services: tuple[Service, ...], keycloak: Service, stopping: asyncio.Event
) -> int:
    children: list[Child] = []
    try:
        for service in services:
            if stopping.is_set():
                return 0
            if await asyncio.to_thread(port_in_use, service.port):
                raise StartupError(f"{service.url} is already in use")

        await ensure_keycloak(keycloak, children, stopping)
        apps: list[Child] = []
        for service in services:
            if stopping.is_set():
                return 0
            child = await start(service)
            children.append(child)
            apps.append(child)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + STARTUP_TIMEOUT
        ready = False
        while not stopping.is_set():
            check_running(apps)
            if not ready:
                health = await asyncio.gather(
                    *(asyncio.to_thread(healthy, service) for service in services)
                )
                check_running(apps)
                if stopping.is_set():
                    break
                if all(health):
                    ready = True
                    urls = "\n".join(
                        f"  {service.name}  {service.url}" for service in services
                    )
                    print(f"Grafy is ready\n{urls}", flush=True)
                elif loop.time() >= deadline:
                    pending = ", ".join(
                        service.name
                        for service, ok in zip(services, health, strict=True)
                        if not ok
                    )
                    raise StartupError(f"Timed out waiting for {pending}")
            await poll_until_stopped(stopping)
        return 0
    except (StartupError, OSError) as exc:
        print(f"[dev] {exc}", file=sys.stderr)
        return 1
    finally:
        await shutdown(children)


def configured_port(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    if raw.isascii() and raw.isdecimal() and len(raw) <= 5 and 1 <= int(raw) <= 65535:
        return int(raw)
    raise StartupError(f"{name} must be a TCP port number")


async def main() -> int:
    try:
        tiler_port = configured_port("TILER_PORT", 8100)
        keycloak_port = configured_port("KEYCLOAK_PORT", 8081)
        if len({3000, 8000, tiler_port, keycloak_port}) != 4:
            raise StartupError("Web, API, tiler, and Keycloak need distinct ports")
    except StartupError as exc:
        print(f"[dev] {exc}", file=sys.stderr)
        return 1

    services = (
        Service("web", ("just", "web", "3000"), 3000, "/"),
        Service("api", ("just", "api"), 8000, "/ready"),
        Service("tiler", ("just", "tiler"), tiler_port, "/health"),
    )
    keycloak = Service(
        "keycloak", ("just", "keycloak-up"), keycloak_port, "/health/ready"
    )
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    return await supervise(services, keycloak, stopping)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

import asyncio
from collections.abc import Sequence
from typing import cast
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from grafy_core.domain.collaboration import ProjectCommand

from .errors import ExecutionTimeoutError
from .library import LibraryClient
from .models import (
    InstanceResult,
    InstanceState,
    NodeCatalog,
    NodeSecretStatus,
    Project,
    ProjectHead,
    Run,
    RunTarget,
    SubmittedCommands,
    UploadItem,
)
from .transport import HttpTransport


def _items(payload: object) -> list[object]:
    if not isinstance(payload, list):
        raise TypeError(f"Expected a JSON array, got {type(payload).__name__}")
    return cast(list[object], payload)


def _mapping(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object, got {type(payload).__name__}")
    return cast(dict[str, object], payload)


class CatalogClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def get(self, workspace_id: UUID) -> NodeCatalog:
        payload = await self._transport.request_json(
            operation="get workspace node catalog",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/nodes",
        )
        return NodeCatalog.model_validate(payload)


class ProjectClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def _path(self, workspace_id: UUID, suffix: str = "") -> str:
        return f"/v1/workspaces/{workspace_id}/projects{suffix}"

    async def create(
        self,
        workspace_id: UUID,
        *,
        name: str,
        graph_id: str = "main",
        graph_name: str = "Main",
    ) -> Project:
        payload = await self._transport.request_json(
            operation="create project",
            method="POST",
            path=self._path(workspace_id),
            json_payload={
                "name": name,
                "graph_id": graph_id,
                "graph_name": graph_name,
            },
        )
        return Project.model_validate(payload)

    async def get(self, workspace_id: UUID, project_id: UUID) -> Project:
        payload = await self._transport.request_json(
            operation="get project",
            method="GET",
            path=self._path(workspace_id, f"/{project_id}"),
        )
        return Project.model_validate(payload)

    async def head(self, workspace_id: UUID, project_id: UUID) -> ProjectHead:
        payload = await self._transport.request_json(
            operation="get project head",
            method="GET",
            path=self._path(workspace_id, f"/{project_id}/head"),
        )
        return ProjectHead.model_validate(payload)

    async def submit_commands(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        head: ProjectHead,
        commands: Sequence[ProjectCommand],
        command_id: UUID | None = None,
    ) -> SubmittedCommands:
        """Apply a batch against ``head``; it is accepted or rejected as a whole."""
        if not commands:
            raise ValueError("A command batch must not be empty")
        payload = await self._transport.request_json(
            operation="submit project commands",
            method="POST",
            path=self._path(workspace_id, f"/{project_id}/commands"),
            json_payload={
                "command_id": str(command_id or uuid4()),
                "room_epoch": str(head.room_epoch),
                "observed_sequence": head.collaboration_sequence,
                "commands": [command.model_dump(mode="json") for command in commands],
            },
        )
        return SubmittedCommands.model_validate(payload)

    async def checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        head: ProjectHead,
    ) -> ProjectHead:
        payload = await self._transport.request_json(
            operation="checkpoint project",
            method="POST",
            path=self._path(workspace_id, f"/{project_id}/checkpoints"),
            json_payload={
                "expected_room_epoch": str(head.room_epoch),
                "expected_sequence": head.collaboration_sequence,
            },
        )
        return ProjectHead.model_validate(_mapping(payload)["head"])

    async def configure_secret(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        node_id: str,
        secret_name: str,
        value: SecretStr,
    ) -> NodeSecretStatus:
        secret = value.get_secret_value()
        if secret == "":
            raise ValueError("Node secret value must not be empty")
        payload = await self._transport.request_json(
            operation="configure node secret",
            method="PUT",
            path=self._path(
                workspace_id,
                f"/{project_id}/graphs/{graph_id}/nodes/{node_id}/secrets/"
                f"{secret_name}",
            ),
            json_payload={"value": secret},
            sensitive_values=(secret,),
        )
        return NodeSecretStatus.model_validate(payload)


class RunClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def _path(self, workspace_id: UUID, project_id: UUID, suffix: str = "") -> str:
        return f"/v1/workspaces/{workspace_id}/projects/{project_id}{suffix}"

    async def start(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        targets: Sequence[RunTarget] = (),
    ) -> Run:
        """Ask for ``targets`` (default: every node of the Graph) to become fresh."""
        payload = await self._transport.request_json(
            operation="start run",
            method="POST",
            path=self._path(workspace_id, project_id, "/runs"),
            json_payload={
                "graph_id": graph_id,
                "targets": [target.model_dump(mode="json") for target in targets],
            },
        )
        return Run.model_validate(payload)

    async def get(self, workspace_id: UUID, project_id: UUID, run_id: UUID) -> Run:
        payload = await self._transport.request_json(
            operation=f"get run {run_id}",
            method="GET",
            path=self._path(workspace_id, project_id, f"/runs/{run_id}"),
        )
        return Run.model_validate(payload)

    async def list(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        active: bool = False,
    ) -> list[Run]:
        payload = await self._transport.request_json(
            operation="list runs",
            method="GET",
            path=self._path(workspace_id, project_id, "/runs"),
            params={"active": "true"} if active else None,
        )
        return [Run.model_validate(item) for item in _items(payload)]

    async def cancel(self, workspace_id: UUID, project_id: UUID, run_id: UUID) -> Run:
        payload = await self._transport.request_json(
            operation=f"cancel run {run_id}",
            method="POST",
            path=self._path(workspace_id, project_id, f"/runs/{run_id}/cancel"),
        )
        return Run.model_validate(payload)

    async def wait(
        self,
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
        *,
        timeout: float,
        poll_interval: float = 0.1,
    ) -> Run:
        if timeout <= 0:
            raise ValueError("Run wait timeout must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        run = await self.get(workspace_id, project_id, run_id)
        while not run.terminal:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ExecutionTimeoutError(
                    operation=f"wait for run {run_id}",
                    detail=f"Timed out after {timeout:g} seconds; status {run.status!r}",
                )
            await asyncio.sleep(min(poll_interval, remaining))
            run = await self.get(workspace_id, project_id, run_id)
        return run

    async def instances(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
    ) -> list[InstanceState]:
        payload = await self._transport.request_json(
            operation="list instance states",
            method="GET",
            path=self._path(workspace_id, project_id, f"/graphs/{graph_id}/instances"),
        )
        return [InstanceState.model_validate(item) for item in _items(payload)]

    async def instance_result(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        node_id: str,
        call_path: Sequence[str] = (),
    ) -> InstanceResult:
        payload = await self._transport.request_json(
            operation="get instance result",
            method="GET",
            path=self._path(workspace_id, project_id, "/instance-result"),
            params={
                "graph_id": graph_id,
                "node_id": node_id,
                "call_path": list(call_path),
            },
        )
        return InstanceResult.model_validate(payload)


class UploadClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def create(
        self,
        workspace_id: UUID,
        *,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> UploadItem:
        if filename.strip() == "":
            raise ValueError("Upload filename must not be blank")
        payload = await self._transport.request_json(
            operation="upload workspace file",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/uploads",
            files={"file": (filename, content, content_type)},
        )
        return UploadItem.model_validate(payload)


class GrafyClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: SecretStr,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = HttpTransport(
            base_url=base_url,
            token=token,
            timeout=timeout,
            transport=transport,
        )
        self.catalog = CatalogClient(self._transport)
        self.projects = ProjectClient(self._transport)
        self.runs = RunClient(self._transport)
        self.uploads = UploadClient(self._transport)
        self.library = LibraryClient(self._transport)

    def __repr__(self) -> str:
        return f"GrafyClient(base_url={self._transport.base_url!r}, token=<redacted>)"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._transport.close()


__all__ = ["CatalogClient", "GrafyClient", "ProjectClient", "RunClient", "UploadClient"]

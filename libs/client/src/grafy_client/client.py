import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from mimetypes import guess_type
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, cast
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from grafy_core.domain.collaboration import (
    AddGraphCommand,
    InGraphCommand,
    ProjectCommand,
    RenameGraphCommand,
    ReplaceDocumentCommand,
)
from grafy_core.domain.credentials import (
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)
from grafy_core.domain.graph_documents import GraphDocument

from .agents import AgentClient
from .errors import ExecutionTimeoutError, GrafyClientError
from .library import LibraryClient
from .models import (
    CatalogPack,
    CredentialVerification,
    GeoFeatureMatch,
    GeoRender,
    ImageInfo,
    ImportedProject,
    InstanceResult,
    InstanceState,
    NodeCatalog,
    NodeSecretDetail,
    NodeSecretStatus,
    Project,
    ProjectCheckpoint,
    ProjectCheckpointSummary,
    ProjectExport,
    ProjectFolder,
    ProjectHead,
    ProjectNodeSecrets,
    ProjectOrganization,
    ProjectSummary,
    Run,
    RunTarget,
    SubmittedCommands,
    TableCellValue,
    TablePage,
    TableSchema,
    UploadItem,
    UploadTarget,
    UserProjectState,
    Workspace,
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


class WorkspaceClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def list(self) -> list[Workspace]:
        """Every Workspace the credential reaches; a token reaches exactly one."""
        payload = await self._transport.request_json(
            operation="list workspaces",
            method="GET",
            path="/v1/workspaces",
        )
        return [Workspace.model_validate(item) for item in _items(payload)]

    async def current(self) -> Workspace:
        """The one Workspace a personal access token is bound to."""
        workspaces = await self.list()
        if len(workspaces) != 1:
            raise GrafyClientError(
                operation="resolve token workspace",
                detail=(
                    f"Expected the token to reach exactly one Workspace, "
                    f"found {len(workspaces)}"
                ),
            )
        return workspaces[0]


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

    async def packs(self, workspace_id: UUID) -> list[CatalogPack]:
        payload = await self._transport.request_json(
            operation="list workspace catalog packs",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/packs",
        )
        return [CatalogPack.model_validate(item) for item in _items(payload)]


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

    async def list(self, workspace_id: UUID) -> list[ProjectSummary]:
        payload = await self._transport.request_json(
            operation="list projects",
            method="GET",
            path=self._path(workspace_id),
        )
        return [
            ProjectSummary.model_validate(item)
            for item in _items(_mapping(payload)["projects"])
        ]

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

    async def export_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        revision: int | None = None,
    ) -> ProjectExport:
        """Export a whole Project (or a specific checkpoint revision) as portable JSON."""
        params = {"revision": revision} if revision is not None else None
        payload = await self._transport.request_json(
            operation="export project",
            method="GET",
            path=self._path(workspace_id, f"/{project_id}/export"),
            params=params,
        )
        return ProjectExport.model_validate(payload)

    async def import_project(
        self,
        workspace_id: UUID,
        export_payload: ProjectExport | Mapping[str, object],
        *,
        name: str | None = None,
        project_id: UUID | None = None,
        command_id: UUID | None = None,
    ) -> ImportedProject:
        """Import a portable Project JSON envelope into ``workspace_id``."""
        body: dict[str, object] = (
            export_payload.model_dump(mode="json")
            if isinstance(export_payload, ProjectExport)
            else dict(export_payload)
        )
        if name is not None:
            body["name"] = name
        if project_id is not None:
            body["project_id"] = str(project_id)
        if command_id is not None:
            body["command_id"] = str(command_id)
        payload = await self._transport.request_json(
            operation="import project",
            method="POST",
            path=self._path(workspace_id, "/import"),
            json_payload=body,
        )
        return ImportedProject.model_validate(payload)

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

    async def apply(
        self,
        workspace_id: UUID,
        project_id: UUID,
        commands: Sequence[ProjectCommand],
        *,
        checkpoint: bool = False,
        command_id: UUID | None = None,
    ) -> SubmittedCommands:
        """Apply a batch against the live head, then optionally checkpoint it.

        The head is read immediately before the batch, so a concurrent edit between
        the two requests surfaces as a 409 rather than overwriting it. With
        ``checkpoint`` the returned head is the checkpointed one.
        """
        head = await self.head(workspace_id, project_id)
        submitted = await self.submit_commands(
            workspace_id,
            project_id,
            head=head,
            commands=commands,
            command_id=command_id,
        )
        if not checkpoint:
            return submitted
        checkpointed = await self.checkpoint(
            workspace_id, project_id, head=submitted.head
        )
        return submitted.model_copy(update={"head": checkpointed})

    async def upsert_graph(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        document: GraphDocument,
        name: str | None = None,
        checkpoint: bool = True,
    ) -> ProjectHead:
        """Make ``graph_id`` hold exactly ``document``, adding the Graph if absent.

        One validated batch: ``add_graph`` for a new Graph, otherwise
        ``replace_document`` (and ``rename_graph`` when ``name`` differs). An
        unchanged Graph sends no batch. The previous document stays reachable
        through the checkpoint history.
        """
        head = await self.head(workspace_id, project_id)
        existing = next(
            (graph for graph in head.document.graphs if graph.id == graph_id), None
        )
        commands: list[ProjectCommand] = []
        if existing is None:
            commands.append(
                AddGraphCommand(
                    graph_id=graph_id, name=name or graph_id, document=document
                )
            )
        else:
            if existing.document != document:
                commands.append(
                    InGraphCommand(
                        graph_id=graph_id,
                        command=ReplaceDocumentCommand(document=document),
                    )
                )
            if name is not None and name != existing.name:
                commands.append(
                    RenameGraphCommand(
                        graph_id=graph_id, name=name, expected_name=existing.name
                    )
                )
        if commands:
            head = (
                await self.submit_commands(
                    workspace_id, project_id, head=head, commands=commands
                )
            ).head
        if checkpoint and head.collaboration_sequence != head.checkpoint_sequence:
            head = await self.checkpoint(workspace_id, project_id, head=head)
        return head

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
        head: ProjectHead,
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
            json_payload={
                "value": secret,
                "expected_head_sequence": head.collaboration_sequence,
            },
            sensitive_values=(secret,),
        )
        return NodeSecretStatus.model_validate(payload)

    async def list_folders(self, workspace_id: UUID) -> list[ProjectFolder]:
        payload = await self._transport.request_json(
            operation="list project folders",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/project-folders",
        )
        return [
            ProjectFolder.model_validate(item)
            for item in _items(_mapping(payload)["folders"])
        ]

    async def create_folder(
        self,
        workspace_id: UUID,
        *,
        name: str,
    ) -> ProjectFolder:
        payload = await self._transport.request_json(
            operation="create project folder",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/project-folders",
            json_payload={"name": name},
        )
        return ProjectFolder.model_validate(payload)

    async def rename_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
        *,
        name: str,
    ) -> ProjectFolder:
        payload = await self._transport.request_json(
            operation="rename project folder",
            method="PATCH",
            path=f"/v1/workspaces/{workspace_id}/project-folders/{folder_id}",
            json_payload={"name": name},
        )
        return ProjectFolder.model_validate(payload)

    async def delete_folder(self, workspace_id: UUID, folder_id: UUID) -> None:
        _ = await self._transport.send(
            operation="delete project folder",
            method="DELETE",
            path=f"/v1/workspaces/{workspace_id}/project-folders/{folder_id}",
        )

    async def assign_folder(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        folder_id: UUID | None,
    ) -> ProjectOrganization:
        payload = await self._transport.request_json(
            operation="assign project folder",
            method="PUT",
            path=self._path(workspace_id, f"/{project_id}/folder"),
            json_payload={
                "folder_id": str(folder_id) if folder_id is not None else None,
            },
        )
        return ProjectOrganization.model_validate(payload)

    async def archive(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization:
        payload = await self._transport.request_json(
            operation="archive project",
            method="PUT",
            path=self._path(workspace_id, f"/{project_id}/archive"),
        )
        return ProjectOrganization.model_validate(payload)

    async def unarchive(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization:
        payload = await self._transport.request_json(
            operation="unarchive project",
            method="DELETE",
            path=self._path(workspace_id, f"/{project_id}/archive"),
        )
        return ProjectOrganization.model_validate(payload)

    async def star(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> UserProjectState:
        payload = await self._transport.request_json(
            operation="star project",
            method="PUT",
            path=self._path(workspace_id, f"/{project_id}/star"),
        )
        return UserProjectState.model_validate(payload)

    async def unstar(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> UserProjectState:
        payload = await self._transport.request_json(
            operation="unstar project",
            method="DELETE",
            path=self._path(workspace_id, f"/{project_id}/star"),
        )
        return UserProjectState.model_validate(payload)

    async def copy(
        self,
        workspace_id: UUID,
        source_project_id: UUID,
        *,
        head: ProjectHead,
        source_workspace_id: UUID | None = None,
        name: str | None = None,
        project_id: UUID | None = None,
        command_id: UUID | None = None,
    ) -> Project:
        body: dict[str, object] = {
            "source_workspace_id": str(source_workspace_id or workspace_id),
            "source_project_id": str(source_project_id),
            "project_id": str(project_id or uuid4()),
            "expected_room_epoch": str(head.room_epoch),
            "expected_sequence": head.collaboration_sequence,
            "command_id": str(command_id or uuid4()),
        }
        if name is not None:
            body["name"] = name
        payload = await self._transport.request_json(
            operation="copy project",
            method="POST",
            path=self._path(workspace_id, "/copies"),
            json_payload=body,
        )
        return Project.model_validate(payload)

    async def list_checkpoints(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectCheckpointSummary]:
        payload = await self._transport.request_json(
            operation="list project checkpoints",
            method="GET",
            path=self._path(workspace_id, f"/{project_id}/checkpoints"),
        )
        return [
            ProjectCheckpointSummary.model_validate(item)
            for item in _items(_mapping(payload)["checkpoints"])
        ]

    async def get_checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
    ) -> ProjectCheckpoint:
        payload = await self._transport.request_json(
            operation="get project checkpoint",
            method="GET",
            path=self._path(workspace_id, f"/{project_id}/checkpoints/{revision}"),
        )
        return ProjectCheckpoint.model_validate(payload)

    async def restore_checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
        *,
        head: ProjectHead,
    ) -> ProjectHead:
        payload = await self._transport.request_json(
            operation="restore project checkpoint",
            method="POST",
            path=self._path(
                workspace_id, f"/{project_id}/checkpoints/{revision}/restore"
            ),
            json_payload={
                "expected_room_epoch": str(head.room_epoch),
                "expected_sequence": head.collaboration_sequence,
            },
        )
        return ProjectHead.model_validate(_mapping(payload)["head"])

    async def secret_status(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str = "main",
    ) -> ProjectNodeSecrets:
        payload = await self._transport.request_json(
            operation="get node secret status",
            method="GET",
            path=self._path(workspace_id, f"/{project_id}/node-secrets"),
            params={"graph_id": graph_id},
        )
        return ProjectNodeSecrets.model_validate(payload)

    async def delete_secret(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        node_id: str,
        secret_name: str,
        head: ProjectHead,
    ) -> None:
        _ = await self._transport.send(
            operation="delete node secret",
            method="DELETE",
            path=self._path(
                workspace_id,
                f"/{project_id}/graphs/{graph_id}/nodes/{node_id}/secrets/"
                f"{secret_name}",
            ),
            params={"expected_head_sequence": head.collaboration_sequence},
        )

    async def set_secret_shared_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        node_id: str,
        secret_name: str,
        mode: SharedCredentialBindingMode | Literal["none"],
        head: ProjectHead,
        credential_id: UUID | None = None,
    ) -> NodeSecretDetail:
        payload = await self._transport.request_json(
            operation="set node secret shared binding",
            method="PUT",
            path=self._path(
                workspace_id,
                f"/{project_id}/graphs/{graph_id}/nodes/{node_id}/secrets/"
                f"{secret_name}/shared-binding",
            ),
            json_payload={
                "mode": str(mode),
                "credential_id": (
                    str(credential_id) if credential_id is not None else None
                ),
                "expected_head_sequence": head.collaboration_sequence,
            },
        )
        return NodeSecretDetail.model_validate(payload)

    async def set_secret_personal_selection(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        node_id: str,
        secret_name: str,
        mode: UserCredentialOverrideMode | Literal["none"],
        credential_id: UUID | None = None,
    ) -> NodeSecretDetail:
        payload = await self._transport.request_json(
            operation="set node secret personal selection",
            method="PUT",
            path=self._path(
                workspace_id,
                f"/{project_id}/graphs/{graph_id}/nodes/{node_id}/secrets/"
                f"{secret_name}/personal-selection",
            ),
            json_payload={
                "mode": str(mode),
                "credential_id": (
                    str(credential_id) if credential_id is not None else None
                ),
            },
        )
        return NodeSecretDetail.model_validate(payload)

    async def verify_secret(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        node_id: str,
        secret_name: str,
        value: SecretStr | None = None,
    ) -> CredentialVerification:
        json_payload: dict[str, object] | None = None
        sensitive_values: tuple[str, ...] = ()
        if value is not None:
            secret = value.get_secret_value()
            if secret == "":
                raise ValueError("Node secret value must not be empty")
            json_payload = {"value": secret}
            sensitive_values = (secret,)
        payload = await self._transport.request_json(
            operation="verify node secret",
            method="POST",
            path=self._path(
                workspace_id,
                f"/{project_id}/graphs/{graph_id}/nodes/{node_id}/secrets/"
                f"{secret_name}/verify",
            ),
            json_payload=json_payload,
            sensitive_values=sensitive_values,
        )
        return CredentialVerification.model_validate(payload)


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
        return [Run.model_validate(item) for item in _items(_mapping(payload)["runs"])]

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
        return [
            InstanceState.model_validate(item)
            for item in _items(_mapping(payload)["instances"])
        ]

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


_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _file_chunks(path: Path, chunk_bytes: int) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := await asyncio.to_thread(handle.read, chunk_bytes):
            yield chunk


class UploadClient:
    """Staged uploads: reserve a target, send the bytes there, then complete.

    The bytes never pass through a JSON body, so a file is limited only by the
    deployment's configured per-file limit, which reserve enforces up front.
    """

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def reserve(
        self,
        workspace_id: UUID,
        *,
        filename: str,
        byte_size: int,
        content_type: str | None = None,
    ) -> UploadTarget:
        if filename.strip() == "":
            raise ValueError("Upload filename must not be blank")
        payload = await self._transport.request_json(
            operation="reserve upload",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/uploads",
            json_payload={
                "filename": filename,
                "byte_size": byte_size,
                "content_type": content_type,
            },
        )
        return UploadTarget.model_validate(payload)

    async def complete(self, workspace_id: UUID, upload_id: str) -> UploadItem:
        payload = await self._transport.request_json(
            operation="complete upload",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/uploads/{upload_id}/complete",
        )
        return UploadItem.model_validate(payload)

    async def upload(
        self,
        workspace_id: UUID,
        source: bytes | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        chunk_bytes: int = _UPLOAD_CHUNK_BYTES,
    ) -> UploadItem:
        """Upload bytes or a file and return the typed artifact ingest produced.

        A ``Path`` is streamed in ``chunk_bytes`` pieces, so a large GeoTIFF is never
        held in memory. ``filename`` defaults to the path's name and decides the
        file format the deployment assigns.
        """
        if isinstance(source, Path):
            resolved_name = filename or source.name
            byte_size = source.stat().st_size
            content: bytes | AsyncIterator[bytes] = _file_chunks(source, chunk_bytes)
        else:
            if filename is None:
                raise ValueError("Uploading bytes requires a filename")
            resolved_name = filename
            byte_size = len(source)
            content = source
        resolved_type = (
            content_type or guess_type(resolved_name)[0] or "application/octet-stream"
        )
        target = await self.reserve(
            workspace_id,
            filename=resolved_name,
            byte_size=byte_size,
            content_type=resolved_type,
        )
        headers: Mapping[str, str] = {
            **target.headers,
            "Content-Length": str(byte_size),
            "Content-Type": resolved_type,
        }
        _ = await self._transport.send(
            operation="send upload bytes",
            method=target.method,
            path=target.url,
            content=content,
            headers=headers,
            authenticate=target.kind == "api",
            sensitive_values=(target.url,) if target.kind == "storage" else (),
        )
        return await self.complete(workspace_id, target.upload_id)


class ArtifactClient:
    """Read-side helpers for table and geo artifacts and raw artifact bytes."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def _path(self, workspace_id: UUID, artifact_id: UUID, suffix: str) -> str:
        return f"/v1/workspaces/{workspace_id}/artifacts/{artifact_id}{suffix}"

    async def content(self, workspace_id: UUID, artifact_id: UUID) -> bytes:
        response = await self._transport.send(
            operation="read artifact content",
            method="GET",
            path=self._path(workspace_id, artifact_id, "/content"),
        )
        return response.content

    async def table_schema(self, workspace_id: UUID, artifact_id: UUID) -> TableSchema:
        payload = await self._transport.request_json(
            operation="read table schema",
            method="GET",
            path=self._path(workspace_id, artifact_id, "/table/schema"),
        )
        return TableSchema.model_validate(payload)

    async def table_page(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        column_offset: int = 0,
        column_limit: int = 25,
        column_ids: Sequence[str] | None = None,
        max_cell_characters: int = 256,
    ) -> TablePage:
        params: dict[str, str | int | list[str]] = {
            "offset": offset,
            "limit": limit,
            "column_offset": column_offset,
            "column_limit": column_limit,
            "max_cell_characters": max_cell_characters,
        }
        if column_ids is not None:
            params["column_ids"] = list(column_ids)
        payload = await self._transport.request_json(
            operation="read table page",
            method="GET",
            path=self._path(workspace_id, artifact_id, "/table/page"),
            params=params,
        )
        return TablePage.model_validate(payload)

    async def table_query(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        filter_rows: Sequence[Mapping[str, str | int | float | bool]] = (),
        highlight_rows: Sequence[Mapping[str, str | int | float | bool]] = (),
        offset: int = 0,
        limit: int = 50,
        column_offset: int = 0,
        column_limit: int = 25,
        column_ids: Sequence[str] | None = None,
        max_cell_characters: int = 256,
    ) -> TablePage:
        """Rows whose fields equal any one of ``filter_rows`` (exact match).

        Each mapping is one row of ``{column_id: value}``; a row matches when every
        field in it matches. ``highlight_rows`` marks rows without filtering.
        """

        def group(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
            if not rows:
                return []
            return [{"rows": [{"values": dict(row)} for row in rows]}]

        payload = await self._transport.request_json(
            operation="query table",
            method="POST",
            path=self._path(workspace_id, artifact_id, "/table/query"),
            json_payload={
                "filter_groups": group(filter_rows),
                "highlight_groups": group(highlight_rows),
                "offset": offset,
                "limit": limit,
                "column_offset": column_offset,
                "column_limit": column_limit,
                "column_ids": None if column_ids is None else list(column_ids),
                "max_cell_characters": max_cell_characters,
            },
        )
        return TablePage.model_validate(payload)

    async def table_cell(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        row_index: int,
        column_id: str,
    ) -> TableCellValue:
        payload = await self._transport.request_json(
            operation="read table cell",
            method="GET",
            path=self._path(workspace_id, artifact_id, "/table/cell"),
            params={"row_index": row_index, "column_id": column_id},
        )
        return TableCellValue.model_validate(payload)

    async def image_info(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        page: int = 0,
    ) -> ImageInfo:
        payload = await self._transport.request_json(
            operation="read image info",
            method="GET",
            path=self._path(workspace_id, artifact_id, "/image/info"),
            params={"page": page},
        )
        return ImageInfo.model_validate(payload)

    async def geo_render(self, workspace_id: UUID, artifact_id: UUID) -> GeoRender:
        payload = await self._transport.request_json(
            operation="read geo render descriptor",
            method="GET",
            path=self._path(workspace_id, artifact_id, "/geo/render"),
        )
        return GeoRender.model_validate(payload)

    async def geo_query(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        rows: Sequence[Mapping[str, str | int | float | bool]],
    ) -> GeoFeatureMatch:
        """Features whose properties equal any one of ``rows`` (exact match)."""
        payload = await self._transport.request_json(
            operation="query geo features",
            method="POST",
            path=self._path(workspace_id, artifact_id, "/geo/query"),
            json_payload={"rows": [{"values": dict(row)} for row in rows]},
        )
        return GeoFeatureMatch.model_validate(payload)


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
        self.workspaces = WorkspaceClient(self._transport)
        self.catalog = CatalogClient(self._transport)
        self.projects = ProjectClient(self._transport)
        self.runs = RunClient(self._transport)
        self.uploads = UploadClient(self._transport)
        self.library = LibraryClient(self._transport)
        self.artifacts = ArtifactClient(self._transport)
        self.agents = AgentClient(self._transport)

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


__all__ = [
    "AgentClient",
    "ArtifactClient",
    "CatalogClient",
    "GrafyClient",
    "ProjectClient",
    "RunClient",
    "UploadClient",
    "WorkspaceClient",
]

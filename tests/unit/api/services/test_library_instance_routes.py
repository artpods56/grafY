from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from grafy_api.artifacts.authoring import ArtifactAuthoringService
from grafy_api.artifacts.content import ArtifactContentService
from grafy_api.http_errors import register_http_error_handlers
from grafy_api.library.models import LibraryItemResponse
from grafy_api.library.service import LibraryService
from grafy_api.v1.routes.auth.dependencies import identity_service, workspace_actor
from grafy_api.v1.routes.library.dependencies import library_service
from grafy_api.v1.routes.library.views import router
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import ArtifactObject, ArtifactRefSequence
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore

WORKSPACE = UUID(int=401)
PROJECT = UUID(int=402)
FINGERPRINT = "a" * 64


class Identity:
    role = WorkspaceRole.EDITOR

    async def authorize(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        capability: WorkspaceCapability,
    ) -> WorkspaceAccess:
        access = WorkspaceAccess(
            actor=actor,
            workspace_id=workspace_id,
            membership=WorkspaceMembership(
                workspace_id=workspace_id, user_id=actor.user_id, role=self.role
            ),
        )
        access.require(capability)
        return access


type LibrarySetup = tuple[
    httpx.AsyncClient, InMemoryUnitOfWork, Identity, ArtifactObject
]


@pytest.fixture
async def setup(tmp_path: Path) -> AsyncIterator[LibrarySetup]:
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 7},
    )
    head = ProjectHead(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        room_epoch=UUID(int=403),
        collaboration_sequence=9,
        checkpoint_sequence=0,
        checkpoint_revision=1,
        name="Project title",
        document=ProjectDocument(
            graphs=(
                GraphDefinition(
                    id="main",
                    name="Main",
                    document=GraphDocument(
                        nodes=(
                            GraphNode(
                                id="value",
                                kind="builtin",
                                operator_id="value.integer",
                                operator_version=1,
                                config={"value": 999},
                                position=GraphPoint(x=0, y=0),
                            ),
                        )
                    ),
                ),
            )
        ),
    )
    async with uow as uow:
        await uow.artifacts.add(artifact)
        await uow.collaboration.add_head(head)
        await uow.results.put_result_if_absent(
            WORKSPACE, FINGERPRINT, {"value": artifact.ref()}, created_at=datetime.now(UTC)
        )
        await uow.commit()
    storage = LocalFileObjectStore(tmp_path)
    specs = {(TEXT_VALUE.key.id, TEXT_VALUE.key.schema_version): TEXT_VALUE}
    service = LibraryService(uow, ArtifactContentService(uow, storage, specs), specs)
    identity = Identity()
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[library_service] = lambda: service
    app.dependency_overrides[identity_service] = lambda: identity
    app.dependency_overrides[workspace_actor] = lambda: ActorContext(
        user_id=UUID(int=404)
    )

    register_http_error_handlers(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, uow, identity, artifact


def body(**overrides: object) -> dict[str, object]:
    value = dict(
        project_id=str(PROJECT),
        graph_id="main",
        node_id="value",
        result_fingerprint=FINGERPRINT,
        output_port="value",
        name="Saved previous value",
    )
    return value | overrides


async def test_saves_exact_prior_result_without_requiring_current_freshness(
    setup: LibrarySetup,
) -> None:
    client, uow, _, artifact = setup
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance", json=body()
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["artifact"]["artifact_id"] == str(artifact.id)
    assert payload["provenance"]["source"] == "instance"
    assert payload["provenance"]["result_fingerprint"] == FINGERPRINT
    assert payload["provenance"]["project_id"] == str(PROJECT)
    assert payload["provenance"]["graph_id"] == "main"
    assert payload["provenance"]["call_path"] == []
    assert payload["provenance"]["output_port"] == "value"
    async with uow as uow:
        result = await uow.results.get_result(WORKSPACE, FINGERPRINT)
        assert result is not None
        assert result.outputs["value"] == artifact.ref()
        stored = await uow.artifacts.get(WORKSPACE, artifact.id)
        assert stored is not None
        assert stored.inline_payload == {"value": 7}


@pytest.mark.parametrize(
    "overrides",
    [
        dict(project_id=str(UUID(int=999))),
        dict(graph_id="missing"),
        dict(node_id="missing"),
        dict(call_path=["missing"]),
        dict(result_fingerprint="b" * 64),
    ],
)
async def test_unknown_or_unscoped_source_is_not_found(
    setup: LibrarySetup, overrides: dict[str, object]
) -> None:
    client, _, _, _ = setup
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance",
        json=body(**overrides),
    )
    assert response.status_code == 404


async def test_cannot_save_another_workspace_result(setup: LibrarySetup) -> None:
    client, _, _, _ = setup
    response = await client.post(
        f"/v1/workspaces/{UUID(int=999)}/library/artifacts/from-instance", json=body()
    )
    assert response.status_code == 404


async def test_library_write_capability_is_required(setup: LibrarySetup) -> None:
    client, _, identity, _ = setup
    identity.role = WorkspaceRole.VIEWER
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance", json=body()
    )
    assert response.status_code == 403


async def test_selects_sequence_item_on_server_and_rejects_invalid_selection(
    setup: LibrarySetup,
) -> None:
    client, uow, _, artifact = setup
    sequence_fingerprint = "c" * 64
    async with uow as uow:
        await uow.results.put_result_if_absent(
            WORKSPACE,
            sequence_fingerprint,
            {
                "value": ArtifactRefSequence.from_key(
                    key=artifact.ref().key(), item_refs=[artifact.ref()]
                )
            },
            created_at=datetime.now(UTC),
        )
        await uow.commit()
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance",
        json=body(result_fingerprint=sequence_fingerprint, item_index=0),
    )
    assert response.status_code == 200
    assert response.json()["provenance"]["item_index"] == 0
    for overrides in [dict(item_index=1), dict(output_port="absent")]:
        response = await client.post(
            f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance",
            json=body(result_fingerprint=sequence_fingerprint, **overrides),
        )
        assert response.status_code == 400


async def test_promotes_an_authored_artifact_once_and_lists_its_download_formats(
    setup: LibrarySetup, tmp_path: Path
) -> None:
    client, uow, _, _ = setup
    storage = LocalFileObjectStore(tmp_path)
    values = ArtifactValues(
        (), uow=uow, storage=storage, bucket="artifacts", storage_backend="local"
    )
    authoring = ArtifactAuthoringService(
        uow,
        storage,
        {("scalar.text", 1): TEXT_VALUE},
        values,
        bucket="artifacts",
        storage_backend="local",
    )
    artifact, _ = await authoring.create(
        WORKSPACE,
        artifact_type="scalar.text",
        schema_version=1,
        payload={"value": "Edited transcription"},
        author_id=UUID(int=404),
        authored_by="user",
    )
    path = f"/v1/workspaces/{WORKSPACE}/library/artifacts"
    response = await client.post(
        f"{path}/from-artifact",
        json={"artifact_id": str(artifact.id), "name": "  Transcription  "},
    )
    assert response.status_code == 200, response.text
    item = LibraryItemResponse.model_validate(response.json())
    assert item.artifact.artifact_id == artifact.id
    assert item.provenance.source == "authored"
    assert item.name == "Transcription"
    assert item.folder_id is None
    assert {entry.format for entry in item.artifact.download_formats} == {
        "json",
        "txt",
    }

    repeated = await client.post(
        f"{path}/from-artifact",
        json={"artifact_id": str(artifact.id), "name": "Another name"},
    )
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
    assert (await client.get(path)).json()["items"] == [response.json()]


@pytest.mark.parametrize("case", ["missing", "cross-workspace", "viewer"])
async def test_artifact_promotion_enforces_scope_and_capability(
    setup: LibrarySetup, case: str
) -> None:
    client, uow, identity, artifact = setup
    workspace_id = UUID(int=999) if case == "cross-workspace" else WORKSPACE
    artifact_id = UUID(int=999) if case == "missing" else artifact.id
    if case == "viewer":
        identity.role = WorkspaceRole.VIEWER
    response = await client.post(
        f"/v1/workspaces/{workspace_id}/library/artifacts/from-artifact",
        json={"artifact_id": str(artifact_id), "name": "Transcription"},
    )
    assert response.status_code == (403 if case == "viewer" else 404)
    async with uow as uow:
        stored = await uow.artifacts.get(WORKSPACE, artifact.id)
        assert stored is not None
        assert stored.library_provenance is None

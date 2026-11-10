from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from grafy_api.http_errors import register_http_error_handlers
from grafy_api.v1.routes.auth.dependencies import identity_service, workspace_actor
from grafy_api.v1.routes.library.dependencies import library_service
from grafy_api.library.service import LibraryService
from grafy_api.v1.routes.library.views import router
from grafy_core.artifacts import ArtifactObject, ArtifactRefSequence
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.kernel.results import StoredResult
from grafy_core.runtime.in_memory import InMemoryUnitOfWork

WORKSPACE = UUID(int=401)
PROJECT = UUID(int=402)
FINGERPRINT = "a" * 64


class Harness(InMemoryUnitOfWork):
    def __init__(self):
        super().__init__()
        self.result = None
        self.head = ProjectHead(
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
        self._collaboration = SimpleNamespace(get_head=self.get_head)
        self._results = SimpleNamespace(
            get_result=self.get_result, artifact_is_referenced=self.referenced
        )
        self._projects = SimpleNamespace(titles_referencing_artifact=self.titles)

    @property
    def collaboration(self):  # type: ignore[override]
        return self._collaboration

    @property
    def results(self):  # type: ignore[override]
        return self._results

    @property
    def projects(self):  # type: ignore[override]
        return self._projects

    async def get_head(self, workspace_id, project_id):
        return self.head if (workspace_id, project_id) == (WORKSPACE, PROJECT) else None

    async def get_result(self, workspace_id, fingerprint):
        return (
            self.result
            if workspace_id == WORKSPACE and fingerprint == FINGERPRINT
            else None
        )

    async def referenced(self, workspace_id, artifact_id):
        return workspace_id == WORKSPACE and self.result is not None

    async def titles(self, workspace_id, artifact_id):
        return {}


class Identity:
    role = WorkspaceRole.EDITOR

    async def authorize(self, *, actor, workspace_id, capability):
        access = WorkspaceAccess(
            actor=actor,
            workspace_id=workspace_id,
            membership=WorkspaceMembership(
                workspace_id=workspace_id, user_id=actor.user_id, role=self.role
            ),
        )
        access.require(capability)
        return access


@pytest.fixture
async def setup():
    uow = Harness()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 7},
    )
    async with uow as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    uow.result = StoredResult(FINGERPRINT, {"value": artifact.ref()}, datetime.now(UTC))
    service = LibraryService(
        uow, SimpleNamespace(export_formats=lambda artifact: []), {}
    )
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


def body(**overrides):
    value = dict(
        project_id=str(PROJECT),
        graph_id="main",
        node_id="value",
        result_fingerprint=FINGERPRINT,
        output_port="value",
        name="Saved previous value",
    )
    return value | overrides


async def test_saves_exact_prior_result_without_requiring_current_freshness(setup):
    client, uow, identity, artifact = setup
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
    assert uow.result.outputs["value"] == artifact.ref()
    assert artifact.inline_payload == {"value": 7}


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
async def test_unknown_or_unscoped_source_is_not_found(setup, overrides):
    client, _, _, _ = setup
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance",
        json=body(**overrides),
    )
    assert response.status_code == 404


async def test_cannot_save_another_workspace_result(setup):
    client, _, _, _ = setup
    response = await client.post(
        f"/v1/workspaces/{UUID(int=999)}/library/artifacts/from-instance", json=body()
    )
    assert response.status_code == 404


async def test_library_write_capability_is_required(setup):
    client, _, identity, _ = setup
    identity.role = WorkspaceRole.VIEWER
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance", json=body()
    )
    assert response.status_code == 403


async def test_selects_sequence_item_on_server_and_rejects_invalid_selection(setup):
    client, uow, _, artifact = setup
    uow.result = StoredResult(
        FINGERPRINT,
        {
            "value": ArtifactRefSequence.from_key(
                key=artifact.ref().key(), item_refs=[artifact.ref()]
            )
        },
        datetime.now(UTC),
    )
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance",
        json=body(item_index=0),
    )
    assert response.status_code == 200
    assert response.json()["provenance"]["item_index"] == 0
    for overrides in [dict(item_index=1), dict(output_port="absent")]:
        response = await client.post(
            f"/v1/workspaces/{WORKSPACE}/library/artifacts/from-instance",
            json=body(**overrides),
        )
        assert response.status_code == 400

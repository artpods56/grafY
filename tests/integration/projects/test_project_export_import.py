"""Integration tests for whole-Project portable JSON export and import routes."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from grafy_core.application.identity import IdentityService
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.collaboration import (
    AddCallNodeCommand,
    AddGraphCommand,
    AddNodeCommand,
    AddOriginCommand,
    InGraphCommand,
    RenameProjectCommand,
)
from grafy_core.domain.graph_documents import (
    AgentContextLink,
    CustomAgentModel,
    GraphAgent,
    GraphDocument,
    GraphNode,
    GraphOrigin,
    GraphPoint,
    GraphPresentationDocument,
    GraphPresentationViewer,
)
from grafy_core.domain.identity import Workspace, WorkspaceKind, WorkspaceRole
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    GRAPH_BOUNDARY_OPERATOR_VERSION,
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    GraphDefinition,
    ProjectDocument,
)
from grafy_api.auth import AuthService
from grafy_api.project_contracts import (
    CheckpointProjectRequest,
    CreateProjectRequest,
    ImportProjectResponse,
    ProjectExportResponse,
    SubmitProjectCommandRequest,
)
from grafy_api.settings import Settings
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenScope,
)
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig

from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.support.identity import WORKSPACE_ID
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values


def _text_node(node_id: str, text: str = "hello") -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id="text.input",
        operator_version=1,
        config={"text": text},
        position=GraphPoint(x=0, y=0),
    )


def test_export_and_import_round_trip_with_multi_graph_and_checkpoints(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects = api.workspace(WORKSPACE_ID).projects
    created = projects.create_ok(CreateProjectRequest(name="Dev pipeline"))
    head = projects.get_head_ok(created.id)

    # Checkpoint 1 has only the empty "main" graph. Now add a second graph, a call
    # node, a text node, and a workspace origin, then checkpoint as revision 2.
    ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey("scalar.text", 1),
    )
    submitted = projects.submit_commands_ok(
        created.id,
        SubmitProjectCommandRequest(
            command_id=uuid4(),
            room_epoch=head.room_epoch,
            observed_sequence=head.collaboration_sequence,
            commands=(
                AddGraphCommand(
                    graph_id="helper",
                    name="Helper",
                    document=GraphDocument(
                        nodes=(
                            GraphNode(
                                kind="builtin",
                                id="in-1",
                                operator_id=GRAPH_INPUT_OPERATOR_ID,
                                operator_version=GRAPH_BOUNDARY_OPERATOR_VERSION,
                                config={"public_name": "prompt"},
                                position=GraphPoint(x=0, y=0),
                            ),
                            GraphNode(
                                kind="builtin",
                                id="out-1",
                                operator_id=GRAPH_OUTPUT_OPERATOR_ID,
                                operator_version=GRAPH_BOUNDARY_OPERATOR_VERSION,
                                config={"public_name": "result"},
                                position=GraphPoint(x=200, y=0),
                            ),
                        )
                    ),
                ),
                InGraphCommand(
                    graph_id="main",
                    command=AddNodeCommand(node=_text_node("n1", "draft")),
                ),
                AddCallNodeCommand(
                    graph_id="main",
                    node_id="call-helper",
                    callee_graph_id="helper",
                    position=GraphPoint(x=150, y=50),
                ),
                InGraphCommand(
                    graph_id="main",
                    command=AddOriginCommand(
                        origin=GraphOrigin(
                            id="origin-1",
                            to_node="call-helper",
                            to_port="prompt",
                            value=ref,
                        )
                    ),
                ),
            ),
        ),
    )
    projects.checkpoint_ok(
        created.id,
        CheckpointProjectRequest(
            expected_room_epoch=submitted.head.room_epoch,
            expected_sequence=submitted.head.collaboration_sequence,
        ),
    )
    # Advance live head past checkpoint 2 with a rename.
    projects.submit_commands_ok(
        created.id,
        SubmitProjectCommandRequest(
            command_id=uuid4(),
            room_epoch=submitted.head.room_epoch,
            observed_sequence=submitted.head.collaboration_sequence,
            commands=(
                RenameProjectCommand(
                    name="Dev pipeline v3", expected_name="Dev pipeline"
                ),
            ),
        ),
    )

    # Export live head.
    live_res = builtin_client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/{created.id}/export"
    )
    assert live_res.status_code == 200
    live_export = ProjectExportResponse.model_validate(live_res.json())
    assert live_export.format == "grafy.project"
    assert live_export.format_version == 1
    assert live_export.name == "Dev pipeline v3"
    assert [g.id for g in live_export.document.graphs] == ["main", "helper"]
    # Origins are stripped on export.
    assert live_export.document.get_graph("main").document.origins == ()
    assert live_export.document.get_graph("main").refresh_generations == {}

    # Export checkpoint revision 1 (original empty single-graph project).
    rev1_res = builtin_client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/{created.id}/export",
        params={"revision": 1},
    )
    assert rev1_res.status_code == 200
    rev1_export = ProjectExportResponse.model_validate(rev1_res.json())
    assert rev1_export.name == "Dev pipeline"
    assert [g.id for g in rev1_export.document.graphs] == ["main"]
    assert rev1_export.document.get_graph("main").document.nodes == ()

    # Import the exported live head as a brand new Project.
    import_payload = live_export.model_dump(mode="json")
    import_payload["name"] = "Prod pipeline"
    import_res = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/import",
        json=import_payload,
    )
    assert import_res.status_code == 201
    imported = ImportProjectResponse.model_validate(import_res.json())
    assert imported.project.id != created.id
    assert imported.project.name == "Prod pipeline"
    assert imported.warnings == []

    imported_head = projects.get_head_ok(imported.project.id)
    assert [g.id for g in imported_head.document.graphs] == ["main", "helper"]
    call_nodes = [
        n
        for n in imported_head.document.get_graph("main").document.nodes
        if n.kind == CALL_NODE_KIND
    ]
    assert len(call_nodes) == 1
    assert call_nodes[0].operator_id == "helper"


def test_import_emits_warnings_for_unknown_operators_credentials_agents_and_sanitization(
    builtin_client: TestClient,
) -> None:
    ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey("scalar.text", 1),
    )
    doc = ProjectDocument(
        graphs=(
            GraphDefinition(
                id="main",
                name="Main",
                document=GraphDocument(
                    nodes=(
                        GraphNode(
                            kind="builtin",
                            id="missing-op",
                            operator_id="custom.not_installed",
                            operator_version=9,
                            config={"upload_key": "stale-upload"},
                            position=GraphPoint(x=0, y=0),
                        ),
                        GraphNode(
                            kind="builtin",
                            id="secret-op",
                            operator_id="mistral.ocr.provider",
                            operator_version=1,
                            config={},
                            position=GraphPoint(x=100, y=0),
                        ),
                    ),
                    origins=(
                        GraphOrigin(
                            id="origin-1",
                            to_node="missing-op",
                            to_port="value",
                            value=ref,
                        ),
                    ),
                    presentation=GraphPresentationDocument(
                        viewers=(
                            GraphPresentationViewer(
                                id="artifact-viewer-card",
                                position=GraphPoint(x=10, y=10),
                                artifact_ref=ref,
                            ),
                        )
                    ),
                    agents=(
                        GraphAgent(
                            id="agent-custom",
                            name="Researcher",
                            model=CustomAgentModel(
                                endpoint="https://api.example.com/v1",
                                model="gpt-4o",
                            ),
                            context=(
                                AgentContextLink(
                                    id="ctx-lib",
                                    kind="library_item",
                                    library_item_id=uuid4(),
                                ),
                                AgentContextLink(
                                    id="ctx-card",
                                    kind="card",
                                    card_id="artifact-viewer-card",
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    response = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/import",
        json={
            "format": "grafy.project",
            "format_version": 1,
            "name": "With warnings",
            "document": doc.model_dump(mode="json"),
        },
    )
    assert response.status_code == 201
    imported = ImportProjectResponse.model_validate(response.json())
    codes = {warning.code for warning in imported.warnings}
    assert codes == {
        "unknown_operator",
        "credentials_required",
        "custom_agent_model",
        "stripped_origins",
        "stripped_artifact_cards",
        "stripped_library_context_links",
        "stripped_card_context_links",
        "stripped_legacy_config_keys",
    }

    # Defense in depth: persisted head has none of the workspace-local state.
    head = GrafyApi(builtin_client).workspace(WORKSPACE_ID).projects.get_head_ok(
        imported.project.id
    )
    main_doc = head.document.get_graph("main").document
    assert main_doc.origins == ()
    assert main_doc.presentation.viewers == ()
    assert main_doc.agents[0].context == ()
    assert "upload_key" not in main_doc.nodes[0].config_dict()


def test_import_rejects_invalid_envelope_and_empty_graphs(
    builtin_client: TestClient,
) -> None:
    bad_version = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/import",
        json={
            "format": "grafy.project",
            "format_version": 2,
            "name": "Bad version",
            "document": {"graphs": []},
        },
    )
    assert bad_version.status_code == 422

    empty_graphs = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/import",
        json={
            "format": "grafy.project",
            "format_version": 1,
            "name": "Empty",
            "document": {"graphs": []},
        },
    )
    assert empty_graphs.status_code == 422


def test_export_and_import_enforce_tenancy_and_pat_capabilities(
    tmp_path: Path,
) -> None:
    database_url = create_db_url(tmp_path, "export_import_scoping")
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                database_url=SecretStr("sqlite+aiosqlite:///"),
            )
        ),
        database_url=SecretStr(database_url),
        workspace=tmp_path / "runtime",
    )

    async def seed() -> tuple[Workspace, Workspace, object]:
        async with db(database_url) as database:
            seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
            owner = await seeder.user(email="owner@example.test", display_name="Owner")
            ws_a = Workspace(slug="ws-a", name="WS A", kind=WorkspaceKind.SHARED)
            ws_b = Workspace(slug="ws-b", name="WS B", kind=WorkspaceKind.SHARED)
            async with SqlAlchemyUnitOfWork(database.sessions) as uow:
                await uow.identity.add_workspace(ws_a)
                await uow.identity.add_workspace(ws_b)
                await uow.commit()
            await seeder.membership(
                user=owner, workspace=ws_a, role=WorkspaceRole.OWNER
            )
            await seeder.membership(
                user=owner, workspace=ws_b, role=WorkspaceRole.OWNER
            )
            auth = AuthService(
                auth=settings.auth,
                public_origin=settings.app.public_origin,
                unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
                identity_service=IdentityService(
                    lambda: SqlAlchemyUnitOfWork(database.sessions)
                ),
            )
            session = await auth.issue_session(owner.id)
            return ws_a, ws_b, session

    ws_a, ws_b, session = asyncio.run(seed())
    csrf = {"Origin": "http://testserver", "X-CSRF-Token": session.csrf_value}

    with client_with_overrides(settings=settings) as client:
        api = GrafyApi(client)
        api.authenticate(session)
        # Create a project in ws_a as owner.
        create_res = client.post(
            f"/v1/workspaces/{ws_a.id}/projects",
            json={"name": "Workspace A project"},
            headers=csrf,
        )
        assert create_res.status_code == 201
        project_id = UUID(create_res.json()["id"])

        # Tenancy: exporting ws_a's project under ws_b returns 404.
        cross_res = client.get(
            f"/v1/workspaces/{ws_b.id}/projects/{project_id}/export",
        )
        assert cross_res.status_code == 404

        # Issue PATs on ws_a with narrow scopes.
        def issue_pat(
            label: str, scopes: tuple[PersonalAccessTokenScope, ...]
        ) -> dict[str, str]:
            api.authenticate(session)
            issued = api.workspace(ws_a.id).create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label=label,
                    scopes=scopes,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=csrf,
            )
            client.cookies.clear()
            return {"Authorization": f"Bearer {issued.token.get_secret_value()}"}

        view_only = issue_pat("view", (PersonalAccessTokenScope.VIEW_PROJECT,))
        create_only = issue_pat(
            "create-only", (PersonalAccessTokenScope.CREATE_PROJECT,)
        )
        create_and_checkpoint = issue_pat(
            "create-and-checkpoint",
            (
                PersonalAccessTokenScope.CREATE_PROJECT,
                PersonalAccessTokenScope.CHECKPOINT_PROJECT,
            ),
        )
        artifacts_only = issue_pat(
            "artifacts-only", (PersonalAccessTokenScope.VIEW_ARTIFACTS,)
        )

        # Export requires VIEW_PROJECT.
        assert (
            client.get(
                f"/v1/workspaces/{ws_a.id}/projects/{project_id}/export",
                headers=artifacts_only,
            ).status_code
            == 403
        )
        export_res = client.get(
            f"/v1/workspaces/{ws_a.id}/projects/{project_id}/export",
            headers=view_only,
        )
        assert export_res.status_code == 200
        exported_json = export_res.json()

        # Import requires BOTH CREATE_PROJECT and CHECKPOINT_PROJECT.
        assert (
            client.post(
                f"/v1/workspaces/{ws_a.id}/projects/import",
                json=exported_json,
                headers=create_only,
            ).status_code
            == 403
        )
        ok_import = client.post(
            f"/v1/workspaces/{ws_a.id}/projects/import",
            json=exported_json,
            headers=create_and_checkpoint,
        )
        assert ok_import.status_code == 201

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from grafy_api.settings import Settings
from grafy_api.app_state import get_resources
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.graph_contracts import (
    CheckpointGraphRequest,
    GraphFolderWriteRequest,
    UpdateSavedGraphRequest,
)
from grafy_api.v1.routes.templates.models import (
    CreateTemplateRequest,
    InstantiateTemplateRequest,
    TemplateResponse,
    UpdateTemplateMetadataRequest,
)
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.collaboration import CollaborativeGraphHead
from grafy_core.domain.execution_history import GraphExecution
from grafy_core.domain.errors import UserDisabledError
from grafy_core.domain.identity import (
    ActorContext,
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraph,
    SavedGraphDocument,
    SavedGraphNode,
    SavedGraphRevision,
)
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.support.clients import GrafyApi
from tests.support.identity import ActorSwitcher
from tests.testkit import client_with_overrides, create_db_url, db


SOURCE_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000701")
DESTINATION_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000702")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000703")
EDITOR_ID = UUID("00000000-0000-0000-0000-000000000704")
VIEWER_ID = UUID("00000000-0000-0000-0000-000000000705")
CROSS_LOCATION_ID = UUID("00000000-0000-0000-0000-000000000706")
VIEWER_BOTH_ID = UUID("00000000-0000-0000-0000-000000000707")
OUTSIDER_ID = UUID("00000000-0000-0000-0000-000000000708")
SOURCE_GRAPH_ID = UUID("00000000-0000-0000-0000-000000000709")
SOURCE_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000710")
CAPABILITY_GRAPH_ID = UUID("00000000-0000-0000-0000-000000000712")


def _source_revision_document() -> SavedGraphDocument:
    return SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                kind="builtin",
                id="source",
                operator_id="example.operator",
                operator_version=1,
                config={
                    "safe_setting": "preserved",
                    "artifact_id": str(SOURCE_ARTIFACT_ID),
                    "upload_key": "source-upload",
                    "uploads": ["source-upload"],
                    "nested": {
                        "artifact_id": str(SOURCE_ARTIFACT_ID),
                        "safe": True,
                    },
                },
                position=GraphPoint(x=1, y=2),
            ),
        )
    )


async def _seed_templates(database_url: str) -> None:
    now = datetime.now(UTC)
    revision_one_document = _source_revision_document()
    revision_two_document = SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                kind="builtin",
                id="changed-later",
                operator_id="example.operator",
                operator_version=1,
                config={"safe_setting": "new source value"},
                position=GraphPoint(x=5, y=6),
            ),
        )
    )
    source_graph = SavedGraph(
        id=SOURCE_GRAPH_ID,
        workspace_id=SOURCE_WORKSPACE_ID,
        created_by_user_id=OWNER_ID,
        name="Changed source",
        document=revision_two_document,
        revision=2,
        created_at=now,
        updated_at=now,
    )
    capability_graph = SavedGraph(
        id=CAPABILITY_GRAPH_ID,
        workspace_id=SOURCE_WORKSPACE_ID,
        created_by_user_id=OWNER_ID,
        name="Graph with a workspace-bound module call",
        document=SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    kind="builtin",
                    id="module-call",
                    operator_id=f"graph.module.{DESTINATION_WORKSPACE_ID}",
                    operator_version=1,
                    config={},
                    position=GraphPoint(x=0, y=0),
                ),
            )
        ),
        created_at=now,
        updated_at=now,
    )
    async with db(database_url) as database:
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            for user_id in (
                OWNER_ID,
                EDITOR_ID,
                VIEWER_ID,
                CROSS_LOCATION_ID,
                VIEWER_BOTH_ID,
                OUTSIDER_ID,
            ):
                await unit_of_work.identity.add_user(
                    User(
                        id=user_id,
                        email=f"{user_id.hex}@example.test",
                        display_name=user_id.hex[-4:],
                    )
                )
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=SOURCE_WORKSPACE_ID,
                    slug="my-graphs",
                    name="My graphs",
                    kind=WorkspaceKind.SHARED,
                )
            )
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=DESTINATION_WORKSPACE_ID,
                    slug="research-team",
                    name="Research team",
                    kind=WorkspaceKind.SHARED,
                )
            )
            for workspace_id, user_id, role in (
                (SOURCE_WORKSPACE_ID, OWNER_ID, WorkspaceRole.OWNER),
                (DESTINATION_WORKSPACE_ID, OWNER_ID, WorkspaceRole.OWNER),
                (SOURCE_WORKSPACE_ID, EDITOR_ID, WorkspaceRole.EDITOR),
                (SOURCE_WORKSPACE_ID, VIEWER_ID, WorkspaceRole.VIEWER),
                (SOURCE_WORKSPACE_ID, CROSS_LOCATION_ID, WorkspaceRole.VIEWER),
                (
                    DESTINATION_WORKSPACE_ID,
                    CROSS_LOCATION_ID,
                    WorkspaceRole.EDITOR,
                ),
                (SOURCE_WORKSPACE_ID, VIEWER_BOTH_ID, WorkspaceRole.VIEWER),
                (DESTINATION_WORKSPACE_ID, VIEWER_BOTH_ID, WorkspaceRole.VIEWER),
            ):
                await unit_of_work.identity.add_membership(
                    WorkspaceMembership(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        role=role,
                    )
                )
            await unit_of_work.graphs.add(source_graph)
            await unit_of_work.graphs.add(capability_graph)
            await unit_of_work.graphs.add_revision(
                SavedGraphRevision(
                    workspace_id=SOURCE_WORKSPACE_ID,
                    graph_id=SOURCE_GRAPH_ID,
                    revision=1,
                    name="Original source",
                    document=revision_one_document,
                    created_at=now,
                )
            )
            await unit_of_work.graphs.add_revision(source_graph.snapshot())
            await unit_of_work.graphs.add_revision(capability_graph.snapshot())
            await unit_of_work.collaboration.add_head(
                CollaborativeGraphHead.for_existing_saved_graph(
                    workspace_id=SOURCE_WORKSPACE_ID,
                    graph_id=SOURCE_GRAPH_ID,
                    name=source_graph.name,
                    document=source_graph.document,
                    checkpoint_revision=source_graph.revision,
                )
            )
            await unit_of_work.collaboration.add_head(
                CollaborativeGraphHead.for_existing_saved_graph(
                    workspace_id=SOURCE_WORKSPACE_ID,
                    graph_id=CAPABILITY_GRAPH_ID,
                    name=capability_graph.name,
                    document=capability_graph.document,
                    checkpoint_revision=capability_graph.revision,
                )
            )
            await unit_of_work.artifacts.add(
                ArtifactObject(
                    id=SOURCE_ARTIFACT_ID,
                    workspace_id=SOURCE_WORKSPACE_ID,
                    artifact_type="scalar.text",
                    schema_version=1,
                    content_type="application/json",
                    storage_backend="inline",
                    inline_payload={"value": "source-only"},
                )
            )
            await unit_of_work.node_secrets.upsert(
                EncryptedNodeSecret(
                    workspace_id=SOURCE_WORKSPACE_ID,
                    graph_id=SOURCE_GRAPH_ID,
                    node_id="source",
                    name="api_key",
                    operator_id="example.operator",
                    operator_version=1,
                    key_id="test-key",
                    aad_version=2,
                    dependency_sha256="d" * 64,
                    nonce=b"n" * 12,
                    ciphertext=b"source-secret",
                    created_at=now,
                    updated_at=now,
                )
            )
            await unit_of_work.execution_history.add(
                GraphExecution(
                    workspace_id=SOURCE_WORKSPACE_ID,
                    execution_id=UUID("00000000-0000-0000-0000-000000000711"),
                    graph_id=SOURCE_GRAPH_ID,
                    graph_revision=1,
                    requested_node_ids=("source",),
                    status="succeeded",
                    created_at=now,
                    started_at=now,
                    finished_at=now,
                )
            )
            await unit_of_work.commit()


@pytest.fixture
def template_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, ActorSwitcher]]:
    database_url = create_db_url(tmp_path, "templates.sqlite3")
    asyncio.run(_seed_templates(database_url))
    actor = ActorSwitcher(user_id=OWNER_ID)
    with client_with_overrides(
        settings=Settings(
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
            auth_cookie_secure=False,
        ),
        overrides={browser_actor: actor.actor, workspace_actor: actor.actor},
    ) as client:
        yield client, actor


def _create_template(
    client: TestClient, *, name: str = "Starter analysis"
) -> TemplateResponse:
    api = GrafyApi(client)
    templates = api.workspace(SOURCE_WORKSPACE_ID).templates
    return templates.create_ok(
        CreateTemplateRequest(
            source_graph_id=SOURCE_GRAPH_ID,
            source_revision=1,
            name=name,
            description="A reusable research starting point",
        )
    )


def test_direct_template_mutation_requires_current_workspace_authority(
    template_client: tuple[TestClient, ActorSwitcher],
) -> None:
    client, actor = template_client
    actor.as_user(OWNER_ID)
    template = _create_template(client)
    service = get_resources(client.app).templates

    with pytest.raises(UserDisabledError):
        asyncio.run(
            service.archive(
                actor=ActorContext(user_id=UUID(int=999)),
                workspace_id=SOURCE_WORKSPACE_ID,
                template_id=template.id,
            )
        )

    stored = asyncio.run(service.get(SOURCE_WORKSPACE_ID, template.id))
    assert stored.is_available


def test_template_snapshot_and_instantiations_remain_independent_and_safe(
    template_client: tuple[TestClient, ActorSwitcher],
) -> None:
    client, actor = template_client
    actor.as_user(OWNER_ID)
    api = GrafyApi(client)
    templates = api.workspace(SOURCE_WORKSPACE_ID).templates
    destination = api.workspace(DESTINATION_WORKSPACE_ID)
    template = _create_template(client)
    folder = destination.graph_folders.create_ok(
        GraphFolderWriteRequest(name="Fieldwork")
    )

    first = templates.instantiate_ok(
        template.id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="Climate review",
            folder_id=folder.id,
        ),
    )
    second = templates.instantiate_ok(
        template.id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="Second review",
            folder_id=folder.id,
        ),
    )
    assert first.graph_id != second.graph_id
    assert first.folder_id == folder.id

    graph = destination.graphs.get(first.graph_id)
    assert graph.status_code == 200, graph.text
    body = graph.json()
    assert body["name"] == "Climate review"
    document = body["document"]
    assert [node["id"] for node in document["nodes"]] == ["source"]
    config = document["nodes"][0]["config"]
    assert config == {
        "safe_setting": "preserved",
        "nested": {"safe": True},
    }
    assert destination.node_secrets.list_secrets(first.graph_id).json()["secrets"] == []
    assert (
        destination.executions.list_graph_executions(first.graph_id).json()["items"]
        == []
    )
    assert destination.artifacts.content(SOURCE_ARTIFACT_ID).status_code == 404

    mutated_nodes = document["nodes"]
    mutated_nodes[0]["config"]["safe_setting"] = "first copy only"
    updated_first = destination.graphs.update(
        first.graph_id,
        UpdateSavedGraphRequest(
            expected_revision=1,
            name=body["name"],
            document=SavedGraphDocument.model_validate(
                {
                    **document,
                    "nodes": mutated_nodes,
                }
            ),
        ),
    )
    assert updated_first.status_code == 200, updated_first.text
    unchanged_second = destination.graphs.get(second.graph_id)
    assert unchanged_second.status_code == 200
    assert unchanged_second.json()["document"]["nodes"][0]["config"][
        "safe_setting"
    ] == ("preserved")

    source = api.workspace(SOURCE_WORKSPACE_ID).graphs.get(SOURCE_GRAPH_ID)
    assert source.status_code == 200
    assert [node["id"] for node in source.json()["document"]["nodes"]] == [
        "changed-later"
    ]

    invalid_capability = templates.create(
        CreateTemplateRequest(
            source_graph_id=CAPABILITY_GRAPH_ID,
            source_revision=1,
            name="Unsafe capability",
        )
    )
    assert invalid_capability.status_code == 422
    assert invalid_capability.json()["detail"] == (
        "This graph cannot be saved as a template"
    )
    assert invalid_capability.json()["code"] == "template.copy_rejected"
    assert "cannot include module operator" not in invalid_capability.text


def test_template_search_metadata_archive_and_role_authorization(
    template_client: tuple[TestClient, ActorSwitcher],
) -> None:
    client, actor = template_client
    actor.as_user(EDITOR_ID)
    api = GrafyApi(client)
    templates = api.workspace(SOURCE_WORKSPACE_ID).templates
    template = _create_template(client, name="Survey starter")
    template_id = template.id

    search = templates.list_ok(q="research")
    assert [item.id for item in search.templates] == [template_id]

    updated = templates.update_metadata_ok(
        template_id,
        UpdateTemplateMetadataRequest(name="Survey field kit"),
    )
    assert updated.name == "Survey field kit"
    assert updated.description is None
    assert templates.archive(template_id).status_code == 403

    actor.as_user(OWNER_ID)
    archived = templates.archive_ok(template_id)
    assert archived.state == "archived"
    assert templates.list_ok().templates == []
    use_archived = templates.instantiate(
        template_id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="Should fail",
        ),
    )
    assert use_archived.status_code == 422
    assert use_archived.json()["detail"] == "Archived templates cannot be used"
    assert use_archived.json()["code"] == "template.unavailable"


def test_using_template_requires_source_read_and_destination_create(
    template_client: tuple[TestClient, ActorSwitcher],
) -> None:
    client, actor = template_client
    actor.as_user(OWNER_ID)
    api = GrafyApi(client)
    templates = api.workspace(SOURCE_WORKSPACE_ID).templates
    template = _create_template(client)
    template_id = template.id

    actor.as_user(OUTSIDER_ID)
    assert templates.list().status_code == 404

    actor.as_user(VIEWER_ID)
    assert templates.get(template_id).status_code == 200
    denied_create = templates.create(
        CreateTemplateRequest(
            source_graph_id=SOURCE_GRAPH_ID,
            source_revision=1,
            name="Denied",
        )
    )
    assert denied_create.status_code == 403

    actor.as_user(VIEWER_BOTH_ID)
    denied = templates.instantiate(
        template_id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="No destination create",
        ),
    )
    assert denied.status_code == 403

    actor.as_user(CROSS_LOCATION_ID)
    allowed = templates.instantiate_ok(
        template_id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="Cross-location copy",
        ),
    )
    assert allowed.destination_workspace_id == DESTINATION_WORKSPACE_ID


def test_template_destination_folder_must_exist_in_destination_workspace(
    template_client: tuple[TestClient, ActorSwitcher],
) -> None:
    client, actor = template_client
    actor.as_user(OWNER_ID)
    api = GrafyApi(client)
    templates = api.workspace(SOURCE_WORKSPACE_ID).templates
    template = _create_template(client)
    response = templates.instantiate(
        template.id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="Missing folder rejected",
            folder_id=UUID("00000000-0000-0000-0000-000000000999"),
        ),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Not found"
    assert response.json()["code"] == "resource.not_found"
    assert "00000000-0000-0000-0000-000000000999" not in response.text


def test_instantiated_template_is_already_checkpointed(
    template_client: tuple[TestClient, ActorSwitcher],
) -> None:
    client, actor = template_client
    actor.as_user(OWNER_ID)
    api = GrafyApi(client)
    template = _create_template(client)
    instantiated = api.workspace(SOURCE_WORKSPACE_ID).templates.instantiate_ok(
        template.id,
        InstantiateTemplateRequest(
            destination_workspace_id=DESTINATION_WORKSPACE_ID,
            name="Checkpointed template",
        ),
    )
    graphs = api.workspace(DESTINATION_WORKSPACE_ID).graphs
    head = graphs.get_head_ok(instantiated.graph_id)
    result = graphs.checkpoint_ok(
        instantiated.graph_id,
        CheckpointGraphRequest(
            expected_room_epoch=head.room_epoch,
            expected_sequence=head.collaboration_sequence,
        ),
    )
    assert result.saved_revision == 1
    assert graphs.get_ok(instantiated.graph_id).revision == 1
    assert result.head.collaboration_sequence == head.collaboration_sequence

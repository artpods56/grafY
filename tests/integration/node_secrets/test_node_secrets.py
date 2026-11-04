import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar, override
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.project_creation import MAIN_GRAPH_ID, stage_project
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.collaboration import InGraphCommand, ReplaceDocumentCommand
from grafy_core.domain.errors import CollaborationHeadConflictError
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphNode,
    GraphPoint,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.projects import Project
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import Plugin, PluginRegistry, NodeSecretInput
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_core.runtime.in_memory import InMemoryUnitOfWork

from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_shared.config import AppConfig
from grafy_workbench.text import TEXT

from grafy_api.services.composition import build_workbench_components
from grafy_api.v1.routes.node_secrets.models import ConfigureNodeSecretRequest
from grafy_api.node_secrets import (
    NodeSecretConfigurationError,
    NodeSecretDeclarationError,
    NodeSecretService,
    NodeSecretValueError,
)
from grafy_api.settings import Settings
from grafy_api.v1.routes.node_secrets.dependencies import node_secret_service

from tests.support.clients import GrafyApi
from tests.support.workbench import workbench_dependency_overrides
from tests.support.identity import (
    TEST_COMMAND_HMAC_KEY,
    TEST_USER_ID,
    browser_actor_override,
)
from tests.testkit import (
    client_with_overrides,
    create_db_url,
    db,
    seed_shared_workspace,
)


class SecretTestConfig(NodeConfig):
    base_url: str
    model: str = "default-model"
    temperature: float = 0.0


class EmptyInput(NodeInput):
    pass


class EmptyOutput(NodeOutput):
    pass


SECRET_TEST_PLUGIN = Plugin(slug="test.node-secrets", title="Node secrets test")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")


@SECRET_TEST_PLUGIN.node(
    operator_id="test.secret-node",
    version=1,
    title="Secret node",
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            config_dependencies=("base_url",),
            title="API key",
        ),
    ),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
class SecretTestNode(Node[SecretTestConfig, EmptyInput, EmptyOutput]):
    captured_contexts: ClassVar[list[NodeExecutionContext]] = []

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: SecretTestConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        self.captured_contexts.append(context)
        return EmptyOutput()


@SECRET_TEST_PLUGIN.node(
    operator_id="test.plain-node",
    version=1,
    title="Plain node",
)
class PlainTestNode(Node[NodeConfig, EmptyInput, EmptyOutput]):
    captured_contexts: ClassVar[list[NodeExecutionContext]] = []

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NodeConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        self.captured_contexts.append(context)
        return EmptyOutput()


def _encryption_key(fill: bytes = b"k") -> SecretStr:
    return SecretStr(base64.b64encode(fill * 32).decode("ascii"))


def _secret_document(
    *,
    base_url: str = "https://llm.example/v1",
    model: str = "default-model",
    temperature: float = 0.0,
    position: GraphPoint | None = None,
    operator_id: str = "test.secret-node",
) -> GraphDocument:
    return GraphDocument(
        nodes=(
            GraphNode(
                kind="builtin",
                id="llm",
                operator_id=operator_id,
                operator_version=1,
                config={
                    "base_url": base_url,
                    "model": model,
                    "temperature": temperature,
                },
                position=position or GraphPoint(x=0, y=0),
            ),
        )
    )


def _project_document(document: GraphDocument) -> ProjectDocument:
    """One Graph under the id every Project route and run reads by default."""

    return ProjectDocument(
        graphs=(GraphDefinition(id=MAIN_GRAPH_ID, name="Main", document=document),)
    )


def _secret_service(
    database: Database,
    registry: PluginRegistry,
    *,
    key: SecretStr | None = None,
) -> NodeSecretService:
    """One server's view of the stored secrets: its own registry and its own key."""

    return NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=registry,
        encryption_key=_encryption_key() if key is None else key,
    )


def _secret_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.install(SECRET_TEST_PLUGIN)
    registry.freeze()
    return registry


@pytest.fixture
async def node_secret_setup(
    tmp_path: Path,
) -> AsyncIterator[tuple[Database, NodeSecretService, PluginRegistry]]:
    database_url = create_db_url(tmp_path, "node-secrets.sqlite3")
    async with db(database_url) as database:
        await seed_shared_workspace(database)
        registry = _secret_registry()
        yield database, _secret_service(database, registry), registry


async def _secret_project(
    database: Database,
    *,
    name: str = "Shared extraction",
    document: GraphDocument | None = None,
) -> UUID:
    """A staged Project whose main Graph holds the document under test."""

    project = Project(
        workspace_id=WORKSPACE_ID,
        name=name,
        created_by_user_id=TEST_USER_ID,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await stage_project(
            project,
            _project_document(document if document is not None else _secret_document()),
            projects=unit_of_work.projects,
            collaboration=unit_of_work.collaboration,
        )
        await unit_of_work.commit()
    return project.id


async def _replace_main_graph(
    database: Database,
    project_id: UUID,
    *,
    document: GraphDocument,
    expected_sequence: int,
) -> int:
    """Move the head with one whole-document replace, and say what sequence it is on.

    A replace carries no compare-and-set of its own, so it is only accepted at the
    sequence the caller read: that promise is what this returns the new sequence for.
    """

    collaboration = CollaborationService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        command_hmac_key=TEST_COMMAND_HMAC_KEY.encode(),
        command_hmac_key_version=1,
    )
    head_before = await collaboration.get_head(
        actor=browser_actor_override(),
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
    )
    submission = await collaboration.submit_commands(
        actor=browser_actor_override(),
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        command_id=uuid4(),
        observed_sequence=head_before.collaboration_sequence,
        observed_room_epoch=head_before.room_epoch,
        commands=(
            InGraphCommand(
                graph_id=MAIN_GRAPH_ID,
                command=ReplaceDocumentCommand(document=document),
            ),
        ),
    )
    assert submission.head.collaboration_sequence == expected_sequence + 1
    return submission.head.collaboration_sequence


async def _stored_secret_count(database: Database, project_id: UUID) -> int:
    async with database.engine.connect() as connection:
        stored = await connection.scalar(
            text("SELECT COUNT(*) FROM node_secrets WHERE project_id = :project_id"),
            {"project_id": project_id.hex},
        )
    return int(stored or 0)


async def test_configured_secret_is_encrypted_and_resolves_only_for_binding(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, service, registry = node_secret_setup
    project_id = await _secret_project(database)
    plaintext = "provider-key-that-must-never-be-returned"

    configured = await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr(plaintext),
        expected_head_sequence=0,
    )
    status = await service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)
    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert configured.configured is True
    assert status.secrets == (configured,)
    assert resolved.get_secret_value() == plaintext
    # A second server holding the same key reads the same binding: the secret is
    # portable, the plaintext is not.
    visitor_service = _secret_service(database, registry)
    visitor_resolved = await visitor_service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )
    assert visitor_resolved.get_secret_value() == plaintext
    async with database.engine.connect() as connection:
        raw = await connection.execute(
            text(
                "SELECT ciphertext, nonce, dependency_sha256, aad_version "
                "FROM node_secrets WHERE project_id = :project_id"
            ),
            {"project_id": project_id.hex},
        )
        row = raw.one()
    assert plaintext.encode("utf-8") not in bytes(row.ciphertext)
    assert len(bytes(row.nonce)) == 12
    assert len(str(row.dependency_sha256)) == 64
    assert row.aad_version == 3

    with pytest.raises(NodeSecretUnavailableError, match="does not match"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://other.example/v1"},
        )


async def test_secret_cache_revision_is_stable_and_changes_on_replacement(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, service, _ = node_secret_setup
    project_id = await _secret_project(database)
    dependencies = {"base_url": "https://llm.example/v1"}
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("first-provider-key"),
        expected_head_sequence=0,
    )

    first = await service.cache_revision(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies=dependencies,
    )
    repeated = await service.cache_revision(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies=dependencies,
    )

    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("second-provider-key"),
        expected_head_sequence=0,
    )
    replaced = await service.cache_revision(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies=dependencies,
    )

    assert len(first) == 64
    assert repeated == first
    assert replaced != first
    assert "first-provider-key" not in first
    assert "second-provider-key" not in replaced


async def test_unrelated_edits_retain_and_resolve_secret(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    """A secret belongs to the node, so moving the head does not move it."""

    database, service, registry = node_secret_setup
    project_id = await _secret_project(database)
    plaintext = "retained-across-unrelated-edits"
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr(plaintext),
        expected_head_sequence=0,
    )

    sequence = await _replace_main_graph(
        database,
        project_id,
        document=_secret_document(
            model="different-model",
            temperature=0.8,
            position=GraphPoint(x=120, y=240),
        ),
        expected_sequence=0,
    )

    status = await service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)
    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert sequence == 1
    assert status.head_sequence == 1
    assert status.secrets[0].configured is True
    assert resolved.get_secret_value() == plaintext
    assert await _stored_secret_count(database, project_id) == 1


async def test_unavailable_operator_keeps_secret_dormant_until_supported_again(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, supported_secrets, registry = node_secret_setup
    project_id = await _secret_project(database)
    await supported_secrets.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("dormant-provider-key"),
        expected_head_sequence=0,
    )
    unavailable_registry = PluginRegistry()
    unavailable_registry.freeze()
    unavailable_secrets = _secret_service(database, unavailable_registry)

    sequence = await _replace_main_graph(
        database,
        project_id,
        document=_secret_document(model="edited-while-dormant"),
        expected_sequence=0,
    )

    status = await unavailable_secrets.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)
    assert status.secrets == ()
    assert status.unresolved_nodes != ()
    assert await _stored_secret_count(database, project_id) == 1
    with pytest.raises(NodeSecretDeclarationError, match="unavailable operator"):
        await unavailable_secrets.resolve_secret(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )

    restored_status = await supported_secrets.status(
        WORKSPACE_ID, project_id, MAIN_GRAPH_ID
    )
    restored = await supported_secrets.resolve_secret(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert sequence == 1
    assert restored_status.secrets[0].configured is True
    assert restored.get_secret_value() == "dormant-provider-key"


async def test_secret_survives_a_head_move_because_only_writes_are_gated(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    """The head sequence guards a write; resolution reads the head that is there."""

    database, service, registry = node_secret_setup
    project_id = await _secret_project(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("head-moving-secret"),
        expected_head_sequence=0,
    )
    await _replace_main_graph(
        database,
        project_id,
        document=_secret_document(model="new-model"),
        expected_sequence=0,
    )

    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert resolved.get_secret_value() == "head-moving-secret"


async def test_a_changed_dependency_makes_the_secret_unusable_until_it_is_reconfigured(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    """A secret belongs to a node under its configuration, not to the slot."""

    database, service, _ = node_secret_setup
    project_id = await _secret_project(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("bound-to-original-endpoint"),
        expected_head_sequence=0,
    )

    sequence = await _replace_main_graph(
        database,
        project_id,
        document=_secret_document(base_url="https://changed.example/v1"),
        expected_sequence=0,
    )
    status = await service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)

    assert sequence == 1
    assert status.head_sequence == 1
    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="does not match"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://changed.example/v1"},
        )

    # Writing it again at the head the node now has is the way back, and it is one
    # row rather than a second one beside the stale ciphertext.
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("bound-to-new-endpoint"),
        expected_head_sequence=1,
    )
    reconfigured = await service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)
    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://changed.example/v1"},
    )

    assert reconfigured.secrets[0].configured is True
    assert resolved.get_secret_value() == "bound-to-new-endpoint"
    assert await _stored_secret_count(database, project_id) == 1


async def test_deleting_a_secret_is_the_way_out_and_is_gated_on_the_head(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, service, _ = node_secret_setup
    project_id = await _secret_project(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("withdrawn-key"),
        expected_head_sequence=0,
    )

    with pytest.raises(CollaborationHeadConflictError):
        await service.remove(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            expected_head_sequence=7,
        )
    assert await _stored_secret_count(database, project_id) == 1

    await service.remove(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        expected_head_sequence=0,
    )
    status = await service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)

    assert await _stored_secret_count(database, project_id) == 0
    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="not configured"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_configure_rejects_stale_head_and_undeclared_slot(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, service, _ = node_secret_setup
    project_id = await _secret_project(database)

    with pytest.raises(CollaborationHeadConflictError):
        await service.configure(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            value=SecretStr("secret"),
            expected_head_sequence=2,
        )
    with pytest.raises(NodeSecretDeclarationError, match="does not declare"):
        await service.configure(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="admin_token",
            value=SecretStr("secret"),
            expected_head_sequence=0,
        )


async def test_status_is_false_and_resolution_fails_with_different_server_key(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, service, registry = node_secret_setup
    project_id = await _secret_project(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("secret"),
        expected_head_sequence=0,
    )
    wrong_key_service = _secret_service(database, registry, key=_encryption_key(b"z"))

    status = await wrong_key_service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)

    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="cannot be decrypted"):
        await wrong_key_service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )
    with pytest.raises(NodeSecretUnavailableError, match="cannot be decrypted"):
        await wrong_key_service.cache_revision(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_operator_version_mismatch_cannot_reuse_stored_secret(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, service, _ = node_secret_setup
    project_id = await _secret_project(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        graph_id=MAIN_GRAPH_ID,
        node_id="llm",
        name="api_key",
        value=SecretStr("version-bound"),
        expected_head_sequence=0,
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE node_secrets SET operator_version = 2 "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id.hex},
        )

    status = await service.status(WORKSPACE_ID, project_id, MAIN_GRAPH_ID)

    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="does not match"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_missing_encryption_key_fails_closed_and_secret_size_is_bounded(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
) -> None:
    database, _, registry = node_secret_setup
    project_id = await _secret_project(database)
    missing_key_service = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=registry,
        encryption_key=None,
    )

    with pytest.raises(NodeSecretConfigurationError, match="required"):
        await missing_key_service.configure(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            value=SecretStr("secret"),
            expected_head_sequence=0,
        )
    with pytest.raises(NodeSecretValueError, match="65536"):
        await _secret_service(database, registry).configure(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
            value=SecretStr("x" * 65_537),
            expected_head_sequence=0,
        )


def test_node_secret_routes_scope_to_the_project_and_never_leak_values(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = create_db_url(tmp_path, "routes.sqlite3")
    database = create_database(database_url)
    plaintext = "route-secret-value"
    registry = PluginRegistry()
    registry.install(SECRET_TEST_PLUGIN)
    registry.install(TEXT)
    registry.freeze()

    async def prepare() -> tuple[NodeSecretService, UUID]:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        await seed_shared_workspace(database)
        project_id = await _secret_project(
            database,
            document=GraphDocument(
                nodes=(
                    *_secret_document().nodes,
                    GraphNode(
                        kind="builtin",
                        id="invalid-text",
                        operator_id="text.input",
                        operator_version=1,
                        config={"unexpected": "do-not-log-this-config-value"},
                        position=GraphPoint(x=1, y=1),
                    ),
                )
            ),
        )
        service = _secret_service(database, registry)
        return service, project_id

    service, project_id = asyncio.run(prepare())
    components = build_workbench_components(
        plugin_registry=registry,
        workspace=tmp_path / "route-workbench",
        unit_of_work=InMemoryUnitOfWork(),
        node_secrets=service,
    )
    overrides = {
        **workbench_dependency_overrides(components),
        node_secret_service: lambda: service,
    }
    try:
        with client_with_overrides(
            settings=Settings(
                app=AppConfig(
                    workspace=tmp_path / "workbench",
                    database_url=SecretStr(database_url),
                )
            ),
            overrides=overrides,
        ) as client:
            api = GrafyApi(client)
            secrets = api.workspace(WORKSPACE_ID).node_secrets
            assert secrets.list_secrets_ok(project_id).head_sequence == 0

            configured = secrets.configure_secret_ok(
                project_id,
                MAIN_GRAPH_ID,
                "llm",
                "api_key",
                ConfigureNodeSecretRequest(
                    value=SecretStr(plaintext),
                    expected_head_sequence=0,
                ),
            )
            assert configured.model_dump(mode="json") == {
                "node_id": "llm",
                "name": "api_key",
                "configured": True,
            }

            # Raw, because a SecretStr value would be redacted by model_dump(mode="json"):
            # the write guard is missing, and the value must not be echoed back.
            invalid = client.put(
                f"/v1/workspaces/{WORKSPACE_ID}/projects/{project_id}"
                f"/graphs/{MAIN_GRAPH_ID}/nodes/llm/secrets/api_key",
                json={"value": plaintext},
            )
            assert invalid.status_code == 422
            assert plaintext not in invalid.text

            status = secrets.list_secrets_ok(project_id)
            assert status.model_dump(mode="json") == {
                "project_id": str(project_id),
                "graph_id": MAIN_GRAPH_ID,
                "head_sequence": 0,
                "secrets": [
                    {"node_id": "llm", "name": "api_key", "configured": True},
                ],
                "unresolved_nodes": [
                    {
                        "node_id": "invalid-text",
                        "reason": "invalid_configuration",
                        "status": "unresolved",
                    }
                ],
            }
            assert plaintext not in status.model_dump_json()
            assert "do-not-log-this-config-value" not in status.model_dump_json()
            unresolved_logs = [
                record
                for record in caplog.records
                if record.getMessage() == "node_secret_status_unresolved"
            ]
            assert any(
                getattr(record, "node_id", None) == "invalid-text"
                and getattr(record, "reason", None) == "invalid_configuration"
                for record in unresolved_logs
            )
            assert all(
                "do-not-log-this-config-value" not in repr(record.__dict__)
                for record in caplog.records
            )

            project = api.workspace(WORKSPACE_ID).projects.get_ok(project_id)
            assert project.model_dump_json().count(plaintext) == 0

            deleted = secrets.remove_secret(
                project_id, MAIN_GRAPH_ID, "llm", "api_key", 0
            )
            assert deleted.status_code == 204
            assert deleted.content == b""
            assert secrets.list_secrets_ok(project_id).secrets[0].configured is False
    finally:
        asyncio.run(database.dispose())


def test_empty_secret_value_response_keeps_its_plain_detail(
    node_secret_setup: tuple[Database, NodeSecretService, PluginRegistry],
    tmp_path: Path,
) -> None:
    # The rejected-value message is the whole response body; nothing about the
    # stored secret is added to it now that the HTTP boundary does the translating.
    database, service, _ = node_secret_setup
    project_id = asyncio.run(_secret_project(database))
    components = build_workbench_components(
        plugin_registry=_secret_registry(),
        workspace=tmp_path / "route-workbench",
        unit_of_work=InMemoryUnitOfWork(),
        node_secrets=service,
    )
    with client_with_overrides(
        settings=Settings(
            app=AppConfig(
                workspace=tmp_path / "workbench",
                database_url=SecretStr(create_db_url(tmp_path, "node-secrets.sqlite3")),
            )
        ),
        overrides={
            **workbench_dependency_overrides(components),
            node_secret_service: lambda: service,
        },
    ) as client:
        response = (
            GrafyApi(client)
            .workspace(WORKSPACE_ID)
            .node_secrets.configure_secret(
                project_id,
                MAIN_GRAPH_ID,
                "llm",
                "api_key",
                ConfigureNodeSecretRequest(
                    value=SecretStr(""),
                    expected_head_sequence=0,
                ),
            )
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Node secret value must not be empty"}

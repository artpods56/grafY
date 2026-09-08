import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar, cast, override
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.graph_creation import stage_checkpointed_graph
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraph,
    SavedGraphDocument,
    SavedGraphNode,
    SavedGraphPluginReleasePin,
)
from grafy_core.domain.errors import SavedGraphRevisionConflictError
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_identity import PluginExecutionPolicy
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import NodeSecretInput, Plugin, PluginRegistry
from grafy_core.ports.node_secrets import NodeSecretUnavailableError

from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.v1.routes.executions.models import RunNodeRequest, RunRequest
from grafy_api.services.composition import (
    WorkbenchComponents,
    build_workbench_components,
)
from grafy_api.v1.routes.executions.runtime.errors import GraphExecutionError
from grafy_api.v1.routes.node_secrets.models import ConfigureNodeSecretRequest
from grafy_api.v1.routes.node_secrets.services import (
    NodeSecretConfigurationError,
    NodeSecretDeclarationError,
    NodeSecretService,
    NodeSecretValueError,
)
from grafy_api.settings import Settings
from grafy_api.v1.routes.node_secrets.dependencies import node_secret_service

from tests.support.clients import GrafyApi
from tests.support.system_plugins import (
    SelectedSystemReleaseLookup,
    build_selected_system_plugin_deployment,
)
from tests.support.workbench import workbench_dependency_overrides
from tests.support.identity import TEST_COMMAND_HMAC_KEY, browser_actor_override
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
SAVED_PLUGIN_RELEASE_PIN = SavedGraphPluginReleasePin(
    scope=PluginReleaseScope.SYSTEM,
    slug=SECRET_TEST_PLUGIN.slug,
    revision=1,
)


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


def _build_secret_components(
    *,
    registry: PluginRegistry,
    workspace: Path,
    saved_graphs: SavedGraphService | None = None,
    node_secrets: NodeSecretService | None = None,
) -> WorkbenchComponents:
    deployment = build_selected_system_plugin_deployment((SECRET_TEST_PLUGIN,))
    return build_workbench_components(
        plugin_registry=registry,
        workspace=workspace,
        saved_graphs=saved_graphs,
        node_secrets=node_secrets,
        plugin_releases=cast(PluginReleaseService, deployment.release_lookup),
    )


@pytest.fixture
async def node_secret_setup(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[Database, NodeSecretService, SavedGraphService, PluginRegistry]
]:
    database_url = create_db_url(tmp_path, "node-secrets.sqlite3")
    async with db(database_url) as database:
        await seed_shared_workspace(database)
        registry = PluginRegistry()
        registry.install(SECRET_TEST_PLUGIN)
        registry.freeze()
        saved_graphs = SavedGraphService(
            lambda: SqlAlchemyUnitOfWork(database.sessions),
            registry,
        )
        service = NodeSecretService(
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
            plugin_registry=registry,
            encryption_key=_encryption_key(),
        )
        yield database, service, saved_graphs, registry


async def _saved_secret_graph(
    database: Database,
    *,
    name: str = "Shared extraction",
    document: SavedGraphDocument | None = None,
) -> SavedGraph:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name=name,
        document=document if document is not None else _secret_document(),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await stage_checkpointed_graph(
            graph,
            graphs=unit_of_work.graphs,
            collaboration=unit_of_work.collaboration,
        )
        await unit_of_work.commit()
    return graph


async def _replace_secret_graph(
    database: Database,
    registry: PluginRegistry,
    graph_id: UUID,
    *,
    workspace_id: UUID,
    name: str,
    document: SavedGraphDocument,
    expected_revision: int,
) -> SavedGraph:
    collaboration = CollaborationService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        registry,
        command_hmac_key=TEST_COMMAND_HMAC_KEY.encode(),
        command_hmac_key_version=1,
    )
    graph, head = await collaboration.replace_complete_document(
        actor=browser_actor_override(),
        workspace_id=workspace_id,
        graph_id=graph_id,
        name=name,
        document=document,
        expected_revision=expected_revision,
    )
    assert head.is_fully_checkpointed
    assert head.checkpoint_revision == graph.revision
    assert head.document == graph.document
    return graph


def _secret_document(
    *,
    base_url: str = "https://llm.example/v1",
    model: str = "default-model",
    temperature: float = 0.0,
    position: GraphPoint | None = None,
    plugin_release_pin: SavedGraphPluginReleasePin | None = None,
) -> SavedGraphDocument:
    return SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                kind="plugin" if plugin_release_pin is not None else "builtin",
                id="llm",
                operator_id="test.secret-node",
                operator_version=1,
                config={
                    "base_url": base_url,
                    "model": model,
                    "temperature": temperature,
                },
                position=position or GraphPoint(x=0, y=0),
                plugin_release_pin=plugin_release_pin,
            ),
        )
    )


def _isolated_secret_release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest.from_plugin(SECRET_TEST_PLUGIN)
    capabilities = PluginCapabilityManifest(
        capabilities=(PluginRuntimeCapability.NODE_SECRETS,)
    )
    runtime = PluginRuntimeArtifact(
        object_key="plugin-releases/system/test.node-secrets/runtime.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/system/test.node-secrets/source.tar.gz",
        source_digest="d" * 64,
        lock_digest="e" * 64,
        runtime_profile="python-uv",
        loader_target="tests.integration.node_secrets:SECRET_TEST_PLUGIN",
        runtime_image_digest=runtime.manifest_digest,
        runtime_artifact=runtime,
        published_by_platform_actor="test:secrets",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=None,
            installed_by_platform_actor="test:secrets",
        ),
    )


async def test_configured_secret_is_encrypted_and_resolves_only_for_binding(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    plaintext = "provider-key-that-must-never-be-returned"

    configured = await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr(plaintext),
        expected_graph_revision=graph.revision,
    )
    status = await service.status(WORKSPACE_ID, graph.id)
    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert configured.configured is True
    assert status.secrets == (configured,)
    assert resolved.get_secret_value() == plaintext
    visitor_service = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=registry,
        encryption_key=_encryption_key(),
    )
    visitor_resolved = await visitor_service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )
    assert visitor_resolved.get_secret_value() == plaintext
    async with database.engine.connect() as connection:
        raw = await connection.execute(
            text(
                "SELECT ciphertext, nonce, dependency_sha256, aad_version "
                "FROM node_secrets WHERE graph_id = :graph_id"
            ),
            {"graph_id": graph.id.hex},
        )
        row = raw.one()
    assert plaintext.encode("utf-8") not in bytes(row.ciphertext)
    assert len(bytes(row.nonce)) == 12
    assert len(str(row.dependency_sha256)) == 64
    assert row.aad_version == 2

    with pytest.raises(NodeSecretUnavailableError, match="does not match"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            graph_revision=graph.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://other.example/v1"},
        )


async def test_secret_cache_revision_is_stable_and_changes_on_replacement(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, _ = node_secret_setup
    graph = await _saved_secret_graph(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("first-provider-key"),
        expected_graph_revision=graph.revision,
    )

    first = await service.cache_revision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )
    repeated = await service.cache_revision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("second-provider-key"),
        expected_graph_revision=graph.revision,
    )
    replaced = await service.cache_revision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert len(first) == 64
    assert repeated == first
    assert replaced != first
    assert "first-provider-key" not in first
    assert "second-provider-key" not in replaced


async def test_unrelated_graph_edits_retain_and_resolve_secret(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    plaintext = "retained-across-unrelated-edits"
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr(plaintext),
        expected_graph_revision=graph.revision,
    )

    updated = await _replace_secret_graph(
        database,
        registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name="Renamed extraction",
        document=_secret_document(
            model="different-model",
            temperature=0.8,
            position=GraphPoint(x=120, y=240),
        ),
        expected_revision=1,
    )

    status = await service.status(WORKSPACE_ID, updated.id)
    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        graph_id=updated.id,
        graph_revision=updated.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )
    async with database.engine.connect() as connection:
        stored_count = await connection.scalar(
            text("SELECT COUNT(*) FROM node_secrets WHERE graph_id = :graph_id"),
            {"graph_id": graph.id.hex},
        )

    assert status.graph_revision == 2
    assert status.secrets[0].configured is True
    assert resolved.get_secret_value() == plaintext
    assert stored_count == 1


async def test_unavailable_operator_keeps_secret_dormant_until_supported_again(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, supported_secrets, _, _ = node_secret_setup
    graph = await _saved_secret_graph(database)
    await supported_secrets.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("dormant-provider-key"),
        expected_graph_revision=graph.revision,
    )
    unavailable_registry = PluginRegistry()
    unavailable_registry.freeze()
    unavailable_secrets = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=unavailable_registry,
        encryption_key=_encryption_key(),
    )

    updated = await _replace_secret_graph(
        database,
        unavailable_registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name="Saved while plugin unavailable",
        document=_secret_document(model="edited-while-dormant"),
        expected_revision=graph.revision,
    )

    status = await unavailable_secrets.status(WORKSPACE_ID, updated.id)
    async with database.engine.connect() as connection:
        stored_count = await connection.scalar(
            text("SELECT COUNT(*) FROM node_secrets WHERE graph_id = :graph_id"),
            {"graph_id": graph.id.hex},
        )
    assert status.secrets == ()
    assert stored_count == 1
    with pytest.raises(NodeSecretDeclarationError, match="unavailable operator"):
        await unavailable_secrets.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=updated.id,
            graph_revision=updated.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )

    restored_status = await supported_secrets.status(WORKSPACE_ID, updated.id)
    restored = await supported_secrets.resolve_secret(
        workspace_id=WORKSPACE_ID,
        graph_id=updated.id,
        graph_revision=updated.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert restored_status.secrets[0].configured is True
    assert restored.get_secret_value() == "dormant-provider-key"


async def test_pinned_isolated_operator_uses_release_contract_for_secret_binding(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, _, _, _ = node_secret_setup
    graph = await _saved_secret_graph(
        database,
        name="Isolated extraction",
        document=_secret_document(plugin_release_pin=SAVED_PLUGIN_RELEASE_PIN),
    )
    release = _isolated_secret_release()
    lookup = SelectedSystemReleaseLookup((release,), ())
    host_registry = PluginRegistry()
    host_registry.freeze()
    service = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=host_registry,
        plugin_release_lookup=lookup,
        encryption_key=_encryption_key(),
    )

    configured = await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("isolated-provider-key"),
        expected_graph_revision=graph.revision,
    )
    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert configured.configured is True
    assert resolved.get_secret_value() == "isolated-provider-key"


async def test_secret_resolution_uses_the_pinned_saved_graph_revision(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    original_revision = graph.revision
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("revision-bound-secret"),
        expected_graph_revision=original_revision,
    )
    updated = await _replace_secret_graph(
        database,
        registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name=graph.name,
        document=_secret_document(model="new-model"),
        expected_revision=original_revision,
    )

    resolved = await service.resolve_secret(
        workspace_id=WORKSPACE_ID,
        graph_id=updated.id,
        graph_revision=original_revision,
        node_id="llm",
        name="api_key",
        dependencies={"base_url": "https://llm.example/v1"},
    )

    assert resolved.get_secret_value() == "revision-bound-secret"


async def test_changing_dependency_deletes_secret_and_changing_back_does_not_revive(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("bound-to-original-endpoint"),
        expected_graph_revision=graph.revision,
    )
    updated = await _replace_secret_graph(
        database,
        registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name=graph.name,
        document=_secret_document(base_url="https://changed.example/v1"),
        expected_revision=1,
    )

    status = await service.status(WORKSPACE_ID, updated.id)
    async with database.engine.connect() as connection:
        stored_count = await connection.scalar(
            text("SELECT COUNT(*) FROM node_secrets WHERE graph_id = :graph_id"),
            {"graph_id": graph.id.hex},
        )

    assert status.graph_revision == 2
    assert status.secrets[0].configured is False
    assert stored_count == 0
    with pytest.raises(NodeSecretUnavailableError, match="not configured"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=updated.id,
            graph_revision=updated.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://changed.example/v1"},
        )

    changed_back = await _replace_secret_graph(
        database,
        registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name=graph.name,
        document=_secret_document(),
        expected_revision=2,
    )
    changed_back_status = await service.status(WORKSPACE_ID, changed_back.id)

    assert changed_back_status.graph_revision == 3
    assert changed_back_status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="not configured"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=changed_back.id,
            graph_revision=changed_back.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_removing_and_readding_node_id_does_not_revive_secret(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("must-not-revive"),
        expected_graph_revision=1,
    )

    await _replace_secret_graph(
        database,
        registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name=graph.name,
        document=SavedGraphDocument(),
        expected_revision=1,
    )
    async with database.engine.connect() as connection:
        stored_count = await connection.scalar(
            text("SELECT COUNT(*) FROM node_secrets WHERE graph_id = :graph_id"),
            {"graph_id": graph.id.hex},
        )
    readded = await _replace_secret_graph(
        database,
        registry,
        graph.id,
        workspace_id=WORKSPACE_ID,
        name=graph.name,
        document=_secret_document(),
        expected_revision=2,
    )
    status = await service.status(WORKSPACE_ID, readded.id)

    assert stored_count == 0
    assert status.graph_revision == 3
    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="not configured"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=readded.id,
            graph_revision=readded.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_configure_rejects_stale_revision_and_undeclared_slot(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, _ = node_secret_setup
    graph = await _saved_secret_graph(database)

    with pytest.raises(SavedGraphRevisionConflictError):
        await service.configure(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            node_id="llm",
            name="api_key",
            value=SecretStr("secret"),
            expected_graph_revision=2,
        )
    with pytest.raises(NodeSecretDeclarationError, match="does not declare"):
        await service.configure(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            node_id="llm",
            name="admin_token",
            value=SecretStr("secret"),
            expected_graph_revision=1,
        )


async def test_status_is_false_and_resolution_fails_with_different_server_key(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("secret"),
        expected_graph_revision=graph.revision,
    )
    wrong_key_service = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=registry,
        encryption_key=_encryption_key(b"z"),
    )

    status = await wrong_key_service.status(WORKSPACE_ID, graph.id)

    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="cannot be decrypted"):
        await wrong_key_service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            graph_revision=graph.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )
    with pytest.raises(NodeSecretUnavailableError, match="cannot be decrypted"):
        await wrong_key_service.cache_revision(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            graph_revision=graph.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_operator_version_mismatch_cannot_reuse_stored_secret(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, service, _, _ = node_secret_setup
    graph = await _saved_secret_graph(database)
    await service.configure(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        node_id="llm",
        name="api_key",
        value=SecretStr("version-bound"),
        expected_graph_revision=1,
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE node_secrets SET operator_version = 2 "
                "WHERE graph_id = :graph_id"
            ),
            {"graph_id": graph.id.hex},
        )

    status = await service.status(WORKSPACE_ID, graph.id)

    assert status.secrets[0].configured is False
    with pytest.raises(NodeSecretUnavailableError, match="does not match"):
        await service.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            graph_revision=graph.revision,
            node_id="llm",
            name="api_key",
            dependencies={"base_url": "https://llm.example/v1"},
        )


async def test_missing_encryption_key_fails_closed_and_secret_size_is_bounded(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
) -> None:
    database, _, _, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    missing_key_service = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=registry,
        encryption_key=None,
    )

    with pytest.raises(NodeSecretConfigurationError, match="required"):
        await missing_key_service.configure(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            node_id="llm",
            name="api_key",
            value=SecretStr("secret"),
            expected_graph_revision=graph.revision,
        )
    with pytest.raises(NodeSecretValueError, match="65536"):
        await NodeSecretService(
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
            plugin_registry=registry,
            encryption_key=_encryption_key(),
        ).configure(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            node_id="llm",
            name="api_key",
            value=SecretStr("x" * 65_537),
            expected_graph_revision=graph.revision,
        )


async def test_saved_run_passes_validated_graph_context_to_node(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
    tmp_path: Path,
) -> None:
    database, _, saved_graphs, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    components = _build_secret_components(
        registry=registry,
        workspace=tmp_path / "context-workbench",
        saved_graphs=saved_graphs,
    )
    SecretTestNode.captured_contexts.clear()

    execution = await components.run_graph.run(
        WORKSPACE_ID,
        RunRequest(
            graph_id=graph.id,
            graph_revision=graph.revision,
            secret_graph_id=graph.id,
            secret_graph_revision=graph.revision,
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="llm",
                    operator_id="test.secret-node",
                    operator_version=1,
                    config={
                        "base_url": "https://llm.example/v1",
                        "model": "default-model",
                        "temperature": 0.0,
                    },
                )
            ],
        ),
    )

    assert execution.status == "succeeded"
    assert len(SecretTestNode.captured_contexts) == 1
    context = SecretTestNode.captured_contexts[0]
    assert context.graph_id == graph.id
    assert context.graph_revision == graph.revision
    assert context.secret_graph_id == graph.id
    assert context.secret_graph_revision == graph.revision
    assert context.node_id == "llm"


async def test_dirty_run_uses_saved_secret_binding_without_materialization_context(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
    tmp_path: Path,
) -> None:
    database, _, saved_graphs, registry = node_secret_setup
    graph = await _saved_secret_graph(database)
    components = _build_secret_components(
        registry=registry,
        workspace=tmp_path / "dirty-context-workbench",
        saved_graphs=saved_graphs,
    )
    SecretTestNode.captured_contexts.clear()
    PlainTestNode.captured_contexts.clear()

    execution = await components.run_graph.run(
        WORKSPACE_ID,
        RunRequest(
            secret_graph_id=graph.id,
            secret_graph_revision=graph.revision,
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="llm",
                    operator_id="test.secret-node",
                    operator_version=1,
                    config={
                        "base_url": "https://llm.example/v1",
                        "model": "unsaved-model",
                        "temperature": 1.25,
                    },
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="unsaved-plain",
                    operator_id="test.plain-node",
                    operator_version=1,
                ),
            ],
        ),
    )
    materializations = await components.presenter.materializations_response(
        WORKSPACE_ID,
        graph.id,
        graph.revision,
        await components.materializations.list_for_graph(
            WORKSPACE_ID,
            graph.id,
            graph.revision,
        ),
    )

    assert execution.status == "succeeded"
    secret_context = SecretTestNode.captured_contexts[0]
    assert secret_context.graph_id is None
    assert secret_context.graph_revision is None
    assert secret_context.secret_graph_id == graph.id
    assert secret_context.secret_graph_revision == graph.revision
    plain_context = PlainTestNode.captured_contexts[0]
    assert plain_context.graph_id is None
    assert plain_context.graph_revision is None
    assert plain_context.secret_graph_id is None
    assert plain_context.secret_graph_revision is None
    assert materializations.node_runs == []


async def test_secret_bearing_run_requires_explicit_secret_graph_context(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
    tmp_path: Path,
) -> None:
    _, _, _, registry = node_secret_setup
    components = _build_secret_components(
        registry=registry,
        workspace=tmp_path / "missing-secret-context-workbench",
    )

    with pytest.raises(
        GraphExecutionError,
        match="saved secret graph context.*'llm'",
    ):
        await components.run_graph.run(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="llm",
                        operator_id="test.secret-node",
                        operator_version=1,
                        config={"base_url": "https://llm.example/v1"},
                    )
                ]
            ),
        )


@pytest.mark.parametrize(
    ("binding_case", "message"),
    [
        ("dependency", "saved configuration required by secret input"),
        ("operator", "does not match the saved operator"),
        ("missing", "does not belong to saved graph"),
    ],
)
async def test_dirty_run_rejects_invalid_saved_secret_binding(
    node_secret_setup: tuple[
        Database,
        NodeSecretService,
        SavedGraphService,
        PluginRegistry,
    ],
    tmp_path: Path,
    binding_case: str,
    message: str,
) -> None:
    database, _, saved_graphs, registry = node_secret_setup
    if binding_case == "operator":
        graph = await _saved_secret_graph(
            database,
            name="Different operator",
            document=SavedGraphDocument(
                nodes=(
                    SavedGraphNode(
                        kind="builtin",
                        id="llm",
                        operator_id="test.plain-node",
                        operator_version=1,
                        config={},
                        position=GraphPoint(x=0, y=0),
                    ),
                )
            ),
        )
    else:
        graph = await _saved_secret_graph(database)
    submitted_node_id = "missing" if binding_case == "missing" else "llm"
    base_url = (
        "https://changed.example/v1"
        if binding_case == "dependency"
        else "https://llm.example/v1"
    )
    components = _build_secret_components(
        registry=registry,
        workspace=tmp_path / f"invalid-binding-{binding_case}",
        saved_graphs=saved_graphs,
    )

    with pytest.raises(GraphExecutionError, match=message):
        await components.run_graph.run(
            WORKSPACE_ID,
            RunRequest(
                secret_graph_id=graph.id,
                secret_graph_revision=graph.revision,
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id=submitted_node_id,
                        operator_id="test.secret-node",
                        operator_version=1,
                        config={"base_url": base_url},
                    )
                ],
            ),
        )


def test_node_secret_routes_never_return_secret_value(tmp_path: Path) -> None:
    database_url = create_db_url(tmp_path, "routes.sqlite3")
    database = create_database(database_url)

    async def prepare() -> tuple[NodeSecretService, WorkbenchComponents, str]:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        await seed_shared_workspace(database)
        registry = PluginRegistry()
        registry.install(SECRET_TEST_PLUGIN)
        registry.freeze()
        saved_graphs = SavedGraphService(
            lambda: SqlAlchemyUnitOfWork(database.sessions),
            registry,
        )
        graph = SavedGraph(
            workspace_id=WORKSPACE_ID,
            name="Shared extraction",
            document=_secret_document(),
        )
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await stage_checkpointed_graph(
                graph,
                graphs=unit_of_work.graphs,
                collaboration=unit_of_work.collaboration,
            )
            await unit_of_work.commit()
        service = NodeSecretService(
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
            plugin_registry=registry,
            encryption_key=_encryption_key(),
        )
        components = build_workbench_components(
            plugin_registry=registry,
            workspace=tmp_path / "route-workbench",
            saved_graphs=saved_graphs,
            node_secrets=service,
        )
        return service, components, str(graph.id)

    service, components, graph_id = asyncio.run(prepare())
    overrides = {
        **workbench_dependency_overrides(components),
        node_secret_service: lambda: service,
    }
    plaintext = "route-secret-value"
    try:
        with client_with_overrides(
            settings=Settings(
                workspace=tmp_path / "workbench",
                database_url=SecretStr(database_url),
            ),
            overrides=overrides,
        ) as client:
            api = GrafyApi(client)
            secrets = api.workspace(WORKSPACE_ID).node_secrets
            catalog = api.workspace(WORKSPACE_ID).catalog.list_nodes()
            assert catalog.status_code == 200
            secret_node = next(
                node
                for node in catalog.json()["nodes"]
                if node["operator_id"] == "test.secret-node"
            )
            assert secret_node["secret_inputs"] == [
                {
                    "name": "api_key",
                    "config_dependencies": ["base_url"],
                    "title": "API key",
                    "description": None,
                }
            ]

            configured = secrets.configure_secret(
                UUID(graph_id),
                "llm",
                "api_key",
                ConfigureNodeSecretRequest(
                    value=SecretStr(plaintext),
                    expected_graph_revision=1,
                ),
            )
            assert configured.status_code == 200
            assert configured.json() == {
                "node_id": "llm",
                "name": "api_key",
                "configured": True,
            }
            assert plaintext not in configured.text

            invalid = client.put(
                f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph_id}/nodes/llm/secrets/api_key",
                # Raw: a SecretStr value would be redacted by model_dump(mode="json").
                json={"value": plaintext},
            )
            assert invalid.status_code == 422
            assert plaintext not in invalid.text

            status = secrets.list_secrets(UUID(graph_id))
            assert status.status_code == 200
            assert status.json() == {
                "graph_id": graph_id,
                "graph_revision": 1,
                "secrets": [
                    {
                        "node_id": "llm",
                        "name": "api_key",
                        "configured": True,
                    }
                ],
            }
            assert plaintext not in status.text

            saved_graph = api.workspace(WORKSPACE_ID).graphs.get(UUID(graph_id))
            assert saved_graph.status_code == 200
            assert plaintext not in saved_graph.text

            deleted = secrets.remove_secret(
                UUID(graph_id),
                "llm",
                "api_key",
                expected_graph_revision=1,
            )
            assert deleted.status_code == 204
            assert deleted.content == b""
    finally:
        asyncio.run(database.dispose())

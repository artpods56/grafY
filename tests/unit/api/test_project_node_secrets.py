import base64
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import SecretStr

from grafy_api.node_secrets import NodeSecretService
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import CollaborationHeadConflictError, NotFoundError
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_plugin_llm.openai_compatible import LLM

WORKSPACE = UUID(int=301)
PROJECT = UUID(int=302)
DEPENDENCIES = {"base_url": "https://provider.example/v1"}


class SecretUow:
    def __init__(self):
        self.collaboration = self
        self.node_secrets = self
        self.records = {}
        self.head = ProjectHead(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            room_epoch=UUID(int=303),
            collaboration_sequence=2,
            checkpoint_sequence=0,
            checkpoint_revision=1,
            name="Secrets",
            document=ProjectDocument(
                graphs=(
                    GraphDefinition(
                        id="main",
                        name="Main",
                        document=GraphDocument(
                            nodes=(
                                GraphNode(
                                    id="llm",
                                    kind="builtin",
                                    operator_id="llm.openai_compatible.chat_completion",
                                    operator_version=1,
                                    position=GraphPoint(x=0, y=0),
                                    config=DEPENDENCIES,
                                ),
                            )
                        ),
                    ),
                )
            ),
        )

    async def __aenter__(self):
        self.before = deepcopy(self.records)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.records = self.before

    async def commit(self):
        pass

    async def get_head(self, workspace_id, project_id):
        return self.head if (workspace_id, project_id) == (WORKSPACE, PROJECT) else None

    lock_head = get_head

    async def upsert(self, secret):
        self.records[
            (
                secret.workspace_id,
                secret.project_id,
                secret.graph_id,
                secret.node_id,
                secret.name,
            )
        ] = secret

    async def get(self, workspace_id, project_id, graph_id, node_id, name):
        return self.records.get((workspace_id, project_id, graph_id, node_id, name))

    async def list_for_graph(self, workspace_id, project_id, graph_id):
        return [
            secret
            for key, secret in self.records.items()
            if key[:3] == (workspace_id, project_id, graph_id)
        ]

    async def remove(self, workspace_id, project_id, graph_id, node_id, name):
        self.records.pop((workspace_id, project_id, graph_id, node_id, name), None)


@pytest.fixture
def harness():
    uow = SecretUow()
    registry = PluginRegistry()
    registry.install(LLM)
    service = NodeSecretService(
        unit_of_work_factory=lambda: uow,
        plugin_registry=registry,
        encryption_key=SecretStr(base64.b64encode(b"k" * 32).decode()),
    )
    return uow, service


async def configure(service, **overrides):
    arguments = dict(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        node_id="llm",
        name="api_key",
        value=SecretStr("private"),
        expected_head_sequence=2,
    )
    arguments.update(overrides)
    return await service.configure(**arguments)


def resolution():
    return dict(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        node_id="llm",
        name="api_key",
        dependencies=DEPENDENCIES,
    )


async def test_project_secret_round_trip_and_revoke(harness):
    uow, service = harness
    assert (await service.status(WORKSPACE, PROJECT, "main")).secrets[
        0
    ].configured is False
    await configure(service)
    stored = next(iter(uow.records.values()))
    assert stored.project_id == PROJECT
    assert stored.graph_id == "main"
    assert b"private" not in stored.ciphertext
    assert "private" not in repr(stored)
    assert (
        await service.resolve_secret(**resolution())
    ).get_secret_value() == "private"
    assert (await service.status(WORKSPACE, PROJECT, "main")).secrets[
        0
    ].configured is True
    await service.remove(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        node_id="llm",
        name="api_key",
        expected_head_sequence=2,
    )
    with pytest.raises(NodeSecretUnavailableError, match="not configured"):
        await service.resolve_secret(**resolution())


async def test_project_secret_is_workspace_scoped_and_sequence_guarded(harness):
    uow, service = harness
    with pytest.raises(NotFoundError):
        await configure(service, workspace_id=UUID(int=999))
    with pytest.raises(NotFoundError):
        await configure(service, project_id=UUID(int=999))
    with pytest.raises(NotFoundError):
        await configure(service, graph_id="missing")
    with pytest.raises(CollaborationHeadConflictError):
        await configure(service, expected_head_sequence=1)
    assert uow.records == {}


async def test_secret_revision_tracks_state_and_not_instance_identity(harness):
    uow, service = harness
    await configure(service)
    original = await service.cache_revision(**resolution())
    record = next(iter(uow.records.values()))
    assert (
        replace(
            record, project_id=UUID(int=998), graph_id="other", node_id="renamed"
        ).cache_revision()
        == original
    )
    await configure(service, value=SecretStr("changed"))
    assert await service.cache_revision(**resolution()) != original
    with pytest.raises(NodeSecretUnavailableError, match="does not match"):
        await service.resolve_secret(
            **(resolution() | {"dependencies": {"base_url": "https://other.example"}})
        )

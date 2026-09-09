from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID

import pytest

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.errors import (
    NotFoundError,
)
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraph,
    SavedGraphDocument,
    SavedGraphNode,
    SavedGraphRevision,
)
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.plugins import PluginRegistry
from grafy_core.runtime.in_memory import (
    InMemoryDataStore,
    InMemoryMaterializedNodeOutputsRepository,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")
CREATOR_ID = UUID("00000000-0000-0000-0000-000000000102")


class FakeSavedGraphRepository:
    def __init__(
        self,
        graphs: dict[UUID, SavedGraph],
        revisions: dict[tuple[UUID, int], SavedGraphRevision],
    ) -> None:
        self._graphs = graphs
        self._revisions = revisions
        self.locked_revisions: list[tuple[UUID, UUID, int]] = []

    async def add(self, graph: SavedGraph) -> None:
        self._graphs[graph.id] = graph

    async def add_revision(self, revision: SavedGraphRevision) -> None:
        key = (revision.graph_id, revision.revision)
        if key in self._revisions:
            raise ValueError(f"Saved graph revision already exists: {key}")
        self._revisions[key] = revision

    async def lock_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        expected_revision: int,
    ) -> None:
        self.locked_revisions.append((workspace_id, graph_id, expected_revision))

    async def get(self, workspace_id: UUID, graph_id: UUID) -> SavedGraph | None:
        if (
            self._graphs.get(graph_id) is not None
            and self._graphs[graph_id].workspace_id != workspace_id
        ):
            return None
        return self._graphs.get(graph_id)

    async def get_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        revision: int,
    ) -> SavedGraphRevision | None:
        revision_value = self._revisions.get((graph_id, revision))
        if revision_value is not None and revision_value.workspace_id != workspace_id:
            return None
        return revision_value

    async def list_revisions(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[SavedGraphRevision]:
        return sorted(
            (
                revision
                for (stored_graph_id, _), revision in self._revisions.items()
                if stored_graph_id == graph_id and revision.workspace_id == workspace_id
            ),
            key=lambda revision: revision.revision,
            reverse=True,
        )

    async def list(self, workspace_id: UUID) -> list[SavedGraph]:
        return [
            graph
            for graph in self._graphs.values()
            if graph.workspace_id == workspace_id
        ]

    async def remove(self, workspace_id: UUID, graph: SavedGraph) -> None:
        if graph.workspace_id != workspace_id:
            return
        self._graphs.pop(graph.id, None)


class FakeNodeSecretRepository:
    def __init__(
        self,
        secrets: dict[tuple[UUID, str, str], EncryptedNodeSecret],
    ) -> None:
        self._secrets = secrets

    async def upsert(self, secret: EncryptedNodeSecret) -> None:
        self._secrets[(secret.graph_id, secret.node_id, secret.name)] = secret

    async def get(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        node_id: str,
        name: str,
    ) -> EncryptedNodeSecret | None:
        secret = self._secrets.get((graph_id, node_id, name))
        if secret is not None and secret.workspace_id != workspace_id:
            return None
        return secret

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[EncryptedNodeSecret]:
        return [
            secret
            for (stored_graph_id, _, _), secret in self._secrets.items()
            if stored_graph_id == graph_id and secret.workspace_id == workspace_id
        ]

    async def remove(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        node_id: str,
        name: str,
    ) -> None:
        secret = self._secrets.get((graph_id, node_id, name))
        if secret is not None and secret.workspace_id != workspace_id:
            return
        self._secrets.pop((graph_id, node_id, name), None)


class FakeSavedGraphUnitOfWork:
    def __init__(
        self,
        graphs: dict[UUID, SavedGraph],
        revisions: dict[tuple[UUID, int], SavedGraphRevision],
        secrets: dict[tuple[UUID, str, str], EncryptedNodeSecret],
        materialization_store: InMemoryDataStore,
    ) -> None:
        self.graphs = FakeSavedGraphRepository(graphs, revisions)
        self.node_secrets = FakeNodeSecretRepository(secrets)
        self._materialization_store = materialization_store
        self.materialized_outputs = InMemoryMaterializedNodeOutputsRepository(
            materialization_store
        )
        self._materialization_snapshot = materialization_store.clone()
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self) -> Self:
        self._materialization_snapshot = self._materialization_store.clone()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.commit_count += 1
        self._materialization_snapshot = self._materialization_store.clone()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self._materialization_store.replace_with(self._materialization_snapshot)


class FakeSavedGraphUnitOfWorkFactory:
    def __init__(self) -> None:
        self.graphs: dict[UUID, SavedGraph] = {}
        self.revisions: dict[tuple[UUID, int], SavedGraphRevision] = {}
        self.secrets: dict[tuple[UUID, str, str], EncryptedNodeSecret] = {}
        self.materialization_store = InMemoryDataStore()
        self.plugin_registry = PluginRegistry()
        self.created: list[FakeSavedGraphUnitOfWork] = []

    def __call__(self) -> FakeSavedGraphUnitOfWork:
        unit_of_work = FakeSavedGraphUnitOfWork(
            self.graphs,
            self.revisions,
            self.secrets,
            self.materialization_store,
        )
        self.created.append(unit_of_work)
        return unit_of_work


def _document(node_id: str = "draft-node") -> SavedGraphDocument:
    return SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                kind="builtin",
                id=node_id,
                operator_id="example.operator",
                operator_version=1,
                config={"draft": True},
                position=GraphPoint(x=1.0, y=2.0),
            ),
        )
    )


def _encrypted_secret(graph_id: UUID) -> EncryptedNodeSecret:
    now = datetime.now(UTC)
    return EncryptedNodeSecret(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        node_id="draft-node",
        name="api_key",
        operator_id="example.operator",
        operator_version=1,
        key_id="test-key",
        aad_version=2,
        dependency_sha256="0" * 64,
        nonce=b"n" * 12,
        ciphertext=b"encrypted",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_and_get_are_read_only() -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    saved = SavedGraph(workspace_id=WORKSPACE_ID, name="Saved", document=_document())
    factory.graphs[saved.id] = saved
    service = SavedGraphService(factory, factory.plugin_registry)

    listed = await service.list(WORKSPACE_ID)
    loaded = await service.get(WORKSPACE_ID, saved.id)

    assert listed == [saved]
    assert loaded is saved
    assert [unit_of_work.commit_count for unit_of_work in factory.created] == [0, 0]


@pytest.mark.asyncio
async def test_graph_reads_are_scoped_to_the_requested_workspace() -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    service = SavedGraphService(factory, factory.plugin_registry)
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=CREATOR_ID,
        name="Scoped graph",
        document=_document(),
    )
    factory.graphs[graph.id] = graph
    factory.revisions[(graph.id, 1)] = graph.snapshot()
    other_workspace_id = UUID("00000000-0000-0000-0000-000000000103")

    with pytest.raises(NotFoundError):
        await service.get(other_workspace_id, graph.id)
    with pytest.raises(NotFoundError):
        await service.get_revision(other_workspace_id, graph.id, graph.revision)
    assert await service.list(other_workspace_id) == []


@pytest.mark.asyncio
async def test_get_raises_not_found_for_unknown_graph() -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    service = SavedGraphService(factory, factory.plugin_registry)
    graph_id = UUID("00000000-0000-0000-0000-000000000404")

    with pytest.raises(NotFoundError, match=str(graph_id)):
        await service.get(WORKSPACE_ID, graph_id)

    assert factory.created[-1].commit_count == 0


@pytest.mark.asyncio
async def test_get_and_list_revisions_keep_historical_snapshots() -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    service = SavedGraphService(factory, factory.plugin_registry)
    original = _document("original")
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=CREATOR_ID,
        name="Original",
        document=original,
    )
    factory.graphs[graph.id] = graph
    factory.revisions[(graph.id, 1)] = graph.snapshot()
    replacement = _document("replacement")

    graph.replace(name="Replacement", document=replacement, expected_revision=1)
    factory.revisions[(graph.id, 2)] = graph.snapshot()

    first = await service.get_revision(WORKSPACE_ID, graph.id, 1)
    second = await service.get_revision(WORKSPACE_ID, graph.id, 2)
    listed = await service.list_revisions(WORKSPACE_ID, graph.id)
    assert first.name == "Original"
    assert first.document == original
    assert second.name == "Replacement"
    assert second.document == replacement
    assert listed == [second, first]
    assert [unit.commit_count for unit in factory.created[-3:]] == [0, 0, 0]


@pytest.mark.asyncio
async def test_revision_reads_raise_not_found_for_unknown_values() -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    service = SavedGraphService(factory, factory.plugin_registry)
    graph_id = UUID("00000000-0000-0000-0000-000000000404")

    with pytest.raises(NotFoundError, match=f"{graph_id}@9"):
        await service.get_revision(WORKSPACE_ID, graph_id, 9)
    with pytest.raises(NotFoundError, match=str(graph_id)):
        await service.list_revisions(WORKSPACE_ID, graph_id)


@pytest.mark.asyncio
async def test_replace_preserves_secret_for_unchanged_unavailable_operator() -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    graph = SavedGraph(workspace_id=WORKSPACE_ID, name="Dormant", document=_document())
    secret = _encrypted_secret(graph.id)
    factory.graphs[graph.id] = graph
    factory.secrets[(graph.id, secret.node_id, secret.name)] = secret
    service = SavedGraphService(factory, factory.plugin_registry)

    async with factory() as unit_of_work:
        await service.apply_replacement_in_unit_of_work(
            unit_of_work,
            graph,
            name="Still dormant",
            document=_document(),
            expected_revision=1,
            physically_remove_orphaned_secrets=True,
        )

    assert factory.secrets == {(graph.id, secret.node_id, secret.name): secret}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replacement",
    [
        SavedGraphDocument(),
        SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    kind="builtin",
                    id="draft-node",
                    operator_id="different.operator",
                    operator_version=1,
                    config={},
                    position=GraphPoint(x=1.0, y=2.0),
                ),
            )
        ),
        SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    kind="builtin",
                    id="draft-node",
                    operator_id="example.operator",
                    operator_version=2,
                    config={},
                    position=GraphPoint(x=1.0, y=2.0),
                ),
            )
        ),
    ],
    ids=("node-removed", "operator-changed", "version-changed"),
)
async def test_replace_deletes_dormant_secret_when_node_identity_changes(
    replacement: SavedGraphDocument,
) -> None:
    factory = FakeSavedGraphUnitOfWorkFactory()
    graph = SavedGraph(workspace_id=WORKSPACE_ID, name="Dormant", document=_document())
    secret = _encrypted_secret(graph.id)
    factory.graphs[graph.id] = graph
    factory.secrets[(graph.id, secret.node_id, secret.name)] = secret
    service = SavedGraphService(factory, factory.plugin_registry)

    async with factory() as unit_of_work:
        await service.apply_replacement_in_unit_of_work(
            unit_of_work,
            graph,
            name=graph.name,
            document=replacement,
            expected_revision=1,
            physically_remove_orphaned_secrets=True,
        )

    assert factory.secrets == {}

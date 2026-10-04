from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal, cast
from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import PluginInstallation
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.domain.plugin_revocations import PluginReleaseRevocationError
import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException
from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.execution.admission import ExecutionAdmissionLimiter
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.materializations import MaterializationService
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.execution.preflight import GraphRunContext, GraphRunPreflight
from grafy_api.execution.requests import RunNodeRequest, RunRequest
from grafy_api.execution.run_graph import RunGraph
from grafy_api.plugins.runtime.admission import ReleaseExecutionAdmission
from grafy_api.plugins.runtime.sandbox import PluginSandboxScopeId
from grafy_api.v1.models import PluginReleasePinModel
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.executions.services import RunResultPresenter

# FastAPI constructs the access parameter annotation through a dependency factory.
from grafy_api.v1.routes.executions.views import (
    run_graph,  # pyright: ignore[reportUnknownVariableType]
)
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.execution_history import ActiveGraphExecution
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PlatformPluginActor
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocationReason,
    SystemPluginRevocationDrainError,
)
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import ArtifactWriterRegistry, OutputPersister
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationRequest,
    PluginInvocationResult,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_persistence import schema
from grafy_persistence.adapters.repositories import SqlPluginReleaseRepository
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from sqlalchemy import event, select, update

from tests.unit.persistence.test_transient_fence_ordering import (
    fence_database as _fence_database_fixture,
)

fence_database = _fence_database_fixture


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000001201")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000001202")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000001203")
TEMPLATE_ID = UUID("00000000-0000-0000-0000-000000001204")
ROOM_EPOCH = UUID("00000000-0000-0000-0000-000000001205")
WORKFLOW_RUN_ID = UUID("00000000-0000-0000-0000-000000001206")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000001208")
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def _system_release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug="builtin.text",
        title="Text",
        nodes=(
            PluginNodeContract(
                operator_id="text.concat",
                operator_version=1,
                title="Concat",
                description="Concatenate text.",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    runtime = PluginRuntimeArtifact(
        object_key="plugin-releases/system/builtin.text/runtime.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=3,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/system/builtin.text/source.tar.gz",
        source_digest="d" * 64,
        lock_digest="e" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin_llm.plugin:LLM",
        runtime_image_digest=runtime.manifest_digest,
        runtime_artifact=runtime,
        published_by_platform_actor="test:revocation",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            installed_by_user_id=None,
            installed_by_platform_actor="test:revocation",
        ),
    )


def _graph_document() -> SavedGraphDocument:
    return SavedGraphDocument.model_validate(
        {
            "nodes": [
                {
                    "kind": "builtin",
                    "id": "known",
                    "operator_id": "text.concat",
                    "operator_version": 1,
                    "config": {"separator": " | "},
                    "position": {"x": 12, "y": 34},
                    "layout": {"width": 320},
                },
                {
                    "kind": "builtin",
                    "id": "unknown",
                    "operator_id": "retired.missing",
                    "operator_version": 7,
                    "config": {"opaque": [1, {"x": True}]},
                    "position": {"x": 56, "y": 78},
                },
                {
                    "kind": "module",
                    "id": "module-input",
                    "operator_id": "module.input",
                    "operator_version": 1,
                    "config": {},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "kind": "module",
                    "id": "module-call",
                    "operator_id": "graph.module.call",
                    "operator_version": 2,
                    "config": {},
                    "position": {"x": 1, "y": 1},
                },
            ],
            "edges": [],
        }
    )


def _run_request() -> dict[str, object]:
    document = _graph_document().model_dump(mode="json")
    nodes = document["nodes"]
    assert isinstance(nodes, list)
    run_nodes: list[dict[str, object]] = []
    for node in cast(list[object], nodes):
        assert isinstance(node, dict)
        run_nodes.append(
            {
                "kind": node["kind"],
                "id": node["id"],
                "operator_id": node["operator_id"],
                "operator_version": node["operator_version"],
                "config": node["config"],
            }
        )
    return {"nodes": run_nodes, "edges": [], "scope": "all"}


@pytest.fixture
async def revocation_database(
    tmp_path: Path,
) -> AsyncIterator[tuple[Database, InstalledPluginRelease]]:
    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'revocation.sqlite3'}")
    release = _system_release()
    document = _graph_document()
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            schema.workspaces.insert().values(
                id=WORKSPACE_ID,
                slug="revocation",
                name="Revocation",
                kind="shared",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.plugin_releases.add(release.release)
        await unit_of_work.plugin_releases.add_installation(release.installation)
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(
                release,
                actor_reference="test:revocation",
            )
        )
        await unit_of_work.commit()
    async with database.engine.begin() as connection:
        await connection.execute(
            schema.saved_graphs.insert().values(
                id=GRAPH_ID,
                workspace_id=WORKSPACE_ID,
                name="Legacy graph",
                document=document,
                revision=7,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await connection.execute(
            schema.saved_graph_revisions.insert().values(
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                revision=7,
                name="Legacy graph",
                document=document,
                created_at=NOW,
            )
        )
        await connection.execute(
            schema.collaborative_graph_heads.insert().values(
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                room_epoch=ROOM_EPOCH,
                collaboration_sequence=11,
                checkpoint_sequence=9,
                checkpoint_revision=7,
                name="Legacy graph",
                document=document,
                updated_at=NOW,
            )
        )
        await connection.execute(
            schema.templates.insert().values(
                id=TEMPLATE_ID,
                workspace_id=WORKSPACE_ID,
                source_graph_id=GRAPH_ID,
                source_revision=7,
                source_graph_name="Legacy graph",
                snapshot_document=document,
                name="Legacy template",
                state="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await connection.execute(
            schema.graph_executions.insert().values(
                workspace_id=WORKSPACE_ID,
                execution_id=EXECUTION_ID,
                graph_id=GRAPH_ID,
                graph_revision=7,
                status="cancelled",
                scope="all",
                submitted_request=_run_request(),
                created_at=NOW,
                finished_at=NOW,
            )
        )
        await connection.execute(
            schema.artifact_objects.insert().values(
                id=ARTIFACT_ID,
                workspace_id=WORKSPACE_ID,
                artifact_type="text",
                schema_version=1,
                content_type="text/plain",
                storage_backend="inline",
                inline_payload={"text": "legacy"},
                metadata={
                    "plugin_release": {
                        "scope": "system",
                        "slug": "builtin.text",
                        "revision": 0,
                    }
                },
            )
        )
        await connection.execute(
            schema.invocation_cache_entries.insert().values(
                workspace_id=WORKSPACE_ID,
                key_sha256="f" * 64,
                generation=UUID("00000000-0000-0000-0000-000000001207"),
                outputs={},
                created_at=NOW,
            )
        )
        await connection.execute(
            schema.materialized_node_outputs.insert().values(
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                graph_revision=7,
                node_id="known",
                workflow_run_id=WORKFLOW_RUN_ID,
                outputs={},
                materialized_at=NOW,
            )
        )
    try:
        yield database, release
    finally:
        await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
async def test_system_revocation_requires_durable_execution_drain(
    revocation_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    status: Literal["queued", "running", "cancelling"],
) -> None:
    database, release = revocation_database
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    actor = PlatformPluginActor("cli:security-response")
    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status=status, finished_at=None)
        )

    with pytest.raises(PluginReleaseRevocationError, match="drained execution queue"):
        await releases.revoke_system(
            slug=release.release.slug,
            revision=release.release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=actor,
        )
    assert (
        await releases.get_system_revocation(
            slug=release.release.slug,
            revision=release.release.revision,
        )
        is None
    )

    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="cancelled", finished_at=NOW)
        )
    revoked = await releases.revoke_system(
        slug=release.release.slug,
        revision=release.release.revision,
        reason=PluginReleaseRevocationReason.SECURITY,
        platform_actor=actor,
    )

    assert revoked.installation_id == release.installation.id
    assert revoked.reason is PluginReleaseRevocationReason.SECURITY
    assert revoked.revoked_by_platform_actor == actor.reference


@pytest.fixture
async def execution_database(
    revocation_database: tuple[Database, InstalledPluginRelease],
    fence_database: Database,
) -> tuple[Database, InstalledPluginRelease]:
    source, release = revocation_database
    async with source.engine.connect() as source_connection:
        async with fence_database.engine.begin() as target_connection:
            for table in schema.metadata.sorted_tables:
                rows = (await source_connection.execute(select(table))).mappings().all()
                if rows:
                    await target_connection.execute(
                        table.insert(), [dict(row) for row in rows]
                    )
    return fence_database, release


class GatedPluginInvoker:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests: list[PluginInvocationRequest] = []

    async def invoke(
        self, request: PluginInvocationRequest, /
    ) -> PluginInvocationResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return PluginInvocationResult(outputs={})


class GatedSandboxCleanup:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.scopes: list[PluginSandboxScopeId] = []

    async def close_scope(self, scope_id: PluginSandboxScopeId, /) -> None:
        self.scopes.append(scope_id)
        self.started.set()
        await self.release.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inline", "first"),
    [
        (inline, first)
        for inline in (False, True)
        for first in ("revocation", "preflight", "invocation", "cleanup")
    ]
    + [(True, "cancellation")],
)
async def test_transient_run_and_system_revocation_obey_the_durable_fence(
    execution_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    inline: bool,
) -> None:
    database, release = execution_database
    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="succeeded", finished_at=NOW)
        )
        await connection.execute(
            update(schema.plugin_installations).values(execution_policy="isolated-only")
        )
    uow = SqlAlchemyUnitOfWork(database.sessions)
    storage = LocalFileObjectStore(tmp_path / "objects")
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions), storage, bucket="plugins"
    )
    registry = PluginRegistry()
    invoker = GatedPluginInvoker()
    cleanup = GatedSandboxCleanup()
    if first not in {"cleanup", "cancellation"}:
        cleanup.release.set()
    if first not in {"invocation", "cancellation"}:
        invoker.release.set()
    resolvers = ResolverRegistry([])
    writers = ArtifactWriterRegistry([])
    compiler = GraphCompiler(
        plugin_registry=registry,
        plugin_context=PluginRuntimeContext(
            workspace=tmp_path,
            storage=storage,
            uow=uow,
            bucket="plugins",
        ),
        module_library=None,
        canonical_artifact_conversions={},
        plugin_release_lookup=releases,
        plugin_invoker=invoker,
        release_admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True, runtime_profile="python-uv"
        ),
        build_digest="a" * 64,
    )
    runner = RunGraph(
        plugin_sandboxes=cleanup,
        preflight=GraphRunPreflight(
            plugin_registry=registry, saved_graphs=None, plugin_release_lookup=releases
        ),
        compiler=compiler,
        coordinator=GraphExecutionCoordinator(
            node_execution=NodeExecutionService(
                runtime=NodeRuntime(
                    materializer=InputMaterializer(resolvers),
                    persister=OutputPersister(writers),
                ),
                edge_values=EdgeValueResolver(
                    resolvers=resolvers, writers=writers, unit_of_work=uow
                ),
                node_secrets=UnavailableNodeSecretResolver(),
            )
        ),
        materializations=MaterializationService(
            uow, ArtifactAvailability(uow, storage), None
        ),
    )
    manager = RunExecutionManager(
        runner, execution_history=ExecutionHistoryService(uow, None)
    )
    availability = ArtifactAvailability(uow, storage)
    artifacts = ArtifactService(uow, storage, availability=availability)
    presenter = RunResultPresenter(artifacts, availability)
    limiter = ExecutionAdmissionLimiter(1)
    actor = ActorContext(user_id=UUID(int=1))
    access = WorkspaceAccess(
        actor=actor,
        workspace_id=WORKSPACE_ID,
        membership=WorkspaceMembership(
            workspace_id=WORKSPACE_ID, user_id=actor.user_id, role=WorkspaceRole.OWNER
        ),
    )
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="plugin",
                id="run",
                operator_id="text.concat",
                operator_version=1,
                plugin_release=PluginReleasePinModel(
                    scope=PluginReleaseScope.SYSTEM,
                    slug=release.release.slug,
                    revision=release.release.revision,
                ),
            )
        ]
    )
    preflight_done = asyncio.Event()
    continue_preflight = asyncio.Event()
    drain_checked = asyncio.Event()
    commit_revocation = asyncio.Event()
    insert_issued = asyncio.Event()
    original_validate = GraphRunPreflight.validate
    original_lock = SqlPluginReleaseRepository.lock_system_revocation

    async def pause_preflight(
        self: GraphRunPreflight, workspace_id: UUID, submitted: RunRequest
    ) -> GraphRunContext:
        prepared = await original_validate(self, workspace_id, submitted)
        preflight_done.set()
        await continue_preflight.wait()
        return prepared

    async def pause_revocation(
        self: SqlPluginReleaseRepository,
    ) -> tuple[ActiveGraphExecution, ...]:
        active = await original_lock(self)
        drain_checked.set()
        await commit_revocation.wait()
        return active

    def observe_insert(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        if statement.startswith("INSERT INTO transient_executions"):
            insert_issued.set()

    async def revoke() -> None:
        await releases.revoke_system(
            slug=release.release.slug,
            revision=release.release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=PlatformPluginActor("cli:race"),
        )

    if first == "preflight":
        monkeypatch.setattr(GraphRunPreflight, "validate", pause_preflight)
    if first == "revocation":
        monkeypatch.setattr(
            SqlPluginReleaseRepository, "lock_system_revocation", pause_revocation
        )
        event.listen(
            database.engine.sync_engine, "before_cursor_execute", observe_insert
        )

    async def run_to_completion() -> tuple[str, str | None]:
        if inline:
            try:
                result = await run_graph(
                    request=request,
                    manager=manager,
                    admission_limiter=limiter,
                    presenter=presenter,
                    access=access,
                )
            except HTTPException as exc:
                assert exc.status_code == 422
                return "failed", str(exc.detail)
            return result.status, None
        snapshot = await manager.start(WORKSPACE_ID, request)
        subscription = await manager.subscribe_events(
            WORKSPACE_ID, snapshot.execution_id
        )
        sequence = 0
        while True:
            batch = await subscription.wait(after_sequence=sequence)
            if batch.terminal:
                break
            if batch.events:
                sequence = batch.events[-1].sequence
        completed = await manager.get(WORKSPACE_ID, snapshot.execution_id)
        return completed.status, completed.error

    tasks: list[asyncio.Task[object]] = []
    try:
        async with asyncio.timeout(10):
            if first == "revocation":
                revocation = asyncio.create_task(revoke())
                tasks.append(revocation)
                await drain_checked.wait()
                execution = asyncio.create_task(run_to_completion())
                tasks.append(execution)
                await insert_issued.wait()
                assert not execution.done()
                commit_revocation.set()
                await revocation
            else:
                execution = asyncio.create_task(run_to_completion())
                tasks.append(execution)
                if first == "preflight":
                    await preflight_done.wait()
                    assert invoker.requests == []
                elif first == "cleanup":
                    await cleanup.started.wait()
                    assert len(cleanup.scopes) == 1
                else:
                    await invoker.started.wait()
                    if first == "cancellation":
                        execution.cancel()
                        await cleanup.started.wait()
                with pytest.raises(SystemPluginRevocationDrainError):
                    await revoke()
                assert (
                    await releases.get_system_revocation(
                        slug=release.release.slug, revision=release.release.revision
                    )
                    is None
                )
                continue_preflight.set()
                invoker.release.set()
                cleanup.release.set()
            if first == "cancellation":
                with pytest.raises(asyncio.CancelledError):
                    await execution
                status, error = "cancelled", None
            else:
                status, error = await execution
            if first == "revocation":
                assert status == "failed"
                assert error is not None and "revoked" in error
                assert invoker.requests == []
            else:
                assert status == (
                    "cancelled" if first == "cancellation" else "succeeded"
                ), error
                assert len(invoker.requests) == 1
                await revoke()
            async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
                assert await transaction.execution_history.list_transient() == ()
            lease = limiter.acquire()
            lease.release()
            assert (
                await releases.get_system_revocation(
                    slug=release.release.slug, revision=release.release.revision
                )
                is not None
            )
    finally:
        continue_preflight.set()
        commit_revocation.set()
        invoker.release.set()
        cleanup.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await manager.shutdown()
        await artifacts.close()
        if first == "revocation":
            event.remove(
                database.engine.sync_engine, "before_cursor_execute", observe_insert
            )

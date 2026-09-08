import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from uuid import UUID

import pytest
from sqlalchemy import JSON, Table, func, select, text, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from grafy_api.system_cutover import (
    CutoverRollbackUnit,
    SystemBaselineCutoverService,
    SystemBaselineManifest,
    SystemBaselineOperator,
    SystemBaselineRelease,
    SystemCutoverBlockedError,
    SystemCutoverCommand,
    SystemCutoverError,
    SystemCutoverPreconditionError,
)
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
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
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationError,
    PluginReleaseRevocationReason,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_persistence.adapters.repositories import SqlPluginReleaseRepository
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore


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
        published_by_platform_actor="test:cutover",
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
            installed_by_platform_actor="test:cutover",
        ),
    )


def _baseline(release: InstalledPluginRelease) -> SystemBaselineManifest:
    assert release.runtime_artifact is not None
    assert release.runtime_image_digest is not None
    return SystemBaselineManifest(
        releases=(
            SystemBaselineRelease(
                release_id=release.id,
                slug=release.slug,
                revision=release.revision,
                selection_generation=1,
                source_digest=release.source_digest,
                lock_digest=release.lock_digest,
                descriptor_digest=release.descriptor.digest,
                contract_digest=release.contract_digest,
                capability_digest=release.capability_digest,
                protocol_digest=release.protocol_digest,
                profile_digest=release.profile_digest,
                runtime_image_digest=release.runtime_image_digest,
                runtime_archive_digest=release.runtime_artifact.archive_digest,
                operators=(
                    SystemBaselineOperator(
                        operator_id="text.concat",
                        operator_version=1,
                    ),
                ),
            ),
        )
    )


def _rollback_unit() -> CutoverRollbackUnit:
    return CutoverRollbackUnit(
        rollback_unit_id="backup-2026-08-24T10:00Z",
        database_backup_sha256="1" * 64,
        release_objects_sha256="2" * 64,
        artifact_storage_sha256="3" * 64,
        migration_manifest_sha256="4" * 64,
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
async def cutover_database(
    tmp_path: Path,
) -> AsyncIterator[tuple[Database, InstalledPluginRelease]]:
    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'cutover.sqlite3'}")
    release = _system_release()
    document = _graph_document()
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            schema.workspaces.insert().values(
                id=WORKSPACE_ID,
                slug="cutover",
                name="Cutover",
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
                actor_reference="test:cutover",
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


async def _raw_document(
    database: Database,
    table: Table,
    column_name: str,
) -> dict[str, object]:
    async with database.engine.connect() as connection:
        value = await connection.scalar(select(type_coerce(table.c[column_name], JSON)))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.mark.asyncio
async def test_cutover_backfills_all_stores_without_logical_graph_change_and_is_idempotent(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    dry_run = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )

    assert [store.changed_rows for store in dry_run.stores] == [1, 1, 1, 1, 1]
    assert len(dry_run.unknown_nodes) == 5
    assert sum(store.excluded_module_nodes for store in dry_run.stores) == 10
    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )

    applied = await service.execute(
        SystemCutoverCommand(
            mode="apply",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
            expected_precondition_token=dry_run.precondition_token,
        )
    )

    assert applied.invalidated_invocation_cache_entries == 1
    assert applied.invalidated_materialized_node_outputs == 1
    assert applied.legacy_provenance_marked == 1
    stores = (
        (schema.saved_graphs, "document", "plugin_release_pin"),
        (schema.saved_graph_revisions, "document", "plugin_release_pin"),
        (schema.collaborative_graph_heads, "document", "plugin_release_pin"),
        (schema.templates, "snapshot_document", "plugin_release_pin"),
        (schema.graph_executions, "submitted_request", "plugin_release"),
    )
    for table, column_name, pin_field in stores:
        stored = await _raw_document(database, table, column_name)
        nodes = stored["nodes"]
        assert isinstance(nodes, list)
        typed_nodes = cast(list[object], nodes)
        known = typed_nodes[0]
        unknown = typed_nodes[1]
        assert isinstance(known, dict)
        assert isinstance(unknown, dict)
        assert known[pin_field] == {
            "scope": "system",
            "slug": "builtin.text",
            "revision": 3,
        }
        assert known["config"] == {"separator": " | "}
        assert stored["edges"] == []
        if table is not schema.graph_executions:
            assert known["position"] == {"x": 12.0, "y": 34.0}
            assert known["layout"] == {
                "width": 320.0,
                "body_height": None,
                "appendix_height": None,
            }
        if table is schema.graph_executions:
            expected_nodes = _run_request()["nodes"]
        else:
            expected_nodes = _graph_document().model_dump(mode="json")["nodes"]
        assert isinstance(expected_nodes, list)
        assert unknown == cast(list[object], expected_nodes)[1]

    async with database.engine.connect() as connection:
        graph_state = (
            await connection.execute(
                select(
                    schema.saved_graphs.c.revision,
                    schema.saved_graphs.c.created_at,
                    schema.saved_graphs.c.updated_at,
                )
            )
        ).one()
        assert graph_state == (7, NOW, NOW)
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.invocation_cache_entries)
            )
            == 0
        )
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.materialized_node_outputs)
            )
            == 0
        )
        provenance = await connection.scalar(
            select(type_coerce(schema.artifact_objects.c.metadata, JSON))
        )
        assert provenance == {
            "plugin_release": {
                "status": "legacy_unpinned",
                "recorded": {
                    "scope": "system",
                    "slug": "builtin.text",
                    "revision": 0,
                },
            }
        }

    second_audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )
    assert all(store.changed_rows == 0 for store in second_audit.stores)
    second_apply = await service.execute(
        SystemCutoverCommand(
            mode="apply",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
            expected_precondition_token=second_audit.precondition_token,
        )
    )
    assert second_apply.invalidated_invocation_cache_entries == 0
    assert second_apply.invalidated_materialized_node_outputs == 0


@pytest.mark.asyncio
async def test_cutover_refuses_a_baseline_digest_mismatch_without_rewriting(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    baseline = _baseline(release)
    mismatched_release = baseline.releases[0].model_copy(
        update={"source_digest": "0" * 64}
    )
    mismatched = baseline.model_copy(update={"releases": (mismatched_release,)})

    with pytest.raises(SystemCutoverError, match="digest/identity mismatch"):
        await SystemBaselineCutoverService(database.sessions).execute(
            SystemCutoverCommand(
                mode="dry-run",
                baseline=mismatched,
                rollback_unit=_rollback_unit(),
            )
        )

    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )


@pytest.mark.asyncio
async def test_cutover_refuses_active_executions_and_stale_preconditions(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="queued", finished_at=None)
        )
    with pytest.raises(SystemCutoverBlockedError, match="drained execution queue"):
        await service.execute(
            SystemCutoverCommand(
                mode="apply",
                baseline=_baseline(release),
                rollback_unit=_rollback_unit(),
                expected_precondition_token=audit.precondition_token,
            )
        )
    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="cancelled", finished_at=NOW)
        )
        document = await connection.scalar(select(schema.saved_graphs.c.document))
        assert isinstance(document, SavedGraphDocument)
        changed_document = document.model_dump(mode="json")
        changed_nodes = changed_document["nodes"]
        assert isinstance(changed_nodes, list)
        first_node = cast(list[object], changed_nodes)[0]
        assert isinstance(first_node, dict)
        first_node["config"] = {"separator": "concurrent"}
        changed = SavedGraphDocument.model_validate(changed_document)
        await connection.execute(update(schema.saved_graphs).values(document=changed))
    with pytest.raises(SystemCutoverPreconditionError, match="changed after dry-run"):
        await service.execute(
            SystemCutoverCommand(
                mode="apply",
                baseline=_baseline(release),
                rollback_unit=_rollback_unit(),
                expected_precondition_token=audit.precondition_token,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
async def test_system_revocation_requires_durable_execution_drain(
    cutover_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    status: Literal["queued", "running", "cancelling"],
) -> None:
    database, release = cutover_database
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
            slug=release.slug,
            revision=release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=actor,
        )
    assert (
        await releases.get_system_revocation(
            slug=release.slug,
            revision=release.revision,
        )
        is None
    )

    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="cancelled", finished_at=NOW)
        )
    revoked = await releases.revoke_system(
        slug=release.slug,
        revision=release.revision,
        reason=PluginReleaseRevocationReason.SECURITY,
        platform_actor=actor,
    )

    assert revoked.installation_id == release.installation_id
    assert revoked.reason is PluginReleaseRevocationReason.SECURITY
    assert revoked.revoked_by_platform_actor == actor.reference


@pytest.mark.asyncio
async def test_cutover_transaction_rolls_back_documents_and_cache_deletes_on_error(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TRIGGER fail_template_cutover BEFORE UPDATE ON templates "
                "BEGIN SELECT RAISE(ABORT, 'cutover test failure'); END"
            )
        )
    with pytest.raises(Exception, match="cutover test failure"):
        await service.execute(
            SystemCutoverCommand(
                mode="apply",
                baseline=_baseline(release),
                rollback_unit=_rollback_unit(),
                expected_precondition_token=audit.precondition_token,
            )
        )

    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )
    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.invocation_cache_entries)
            )
            == 1
        )
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.materialized_node_outputs)
            )
            == 1
        )


QUEUED_EXECUTION_ID = UUID("00000000-0000-0000-0000-000000001209")


class _FenceDialectProbe:
    """Records the raw statements the apply maintenance fence issues."""

    def __init__(self, dialect_name: str) -> None:
        self._dialect_name = dialect_name
        self.statements: list[str] = []

    @property
    def dialect(self) -> SimpleNamespace:
        return SimpleNamespace(name=self._dialect_name)

    def get_bind(self) -> "_FenceDialectProbe":
        return self

    async def execute(self, statement: object, *args: object) -> None:
        del args
        self.statements.append(str(statement))


@pytest.mark.asyncio
async def test_postgresql_fence_locks_every_cutover_table_in_fixed_order(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, _ = cutover_database
    probe = _FenceDialectProbe("postgresql")
    # The PostgreSQL fence is statement-level behavior; no PG server is
    # available in unit tests, so the dispatch is probed directly.
    await SystemBaselineCutoverService(
        database.sessions
    )._acquire_apply_maintenance_fence(cast(AsyncSession, probe))  # pyright: ignore[reportPrivateUsage]
    assert probe.statements == [
        f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"
        for table in (
            "plugin_releases",
            "plugin_release_selections",
            "plugin_release_revocations",
            "saved_graphs",
            "saved_graph_revisions",
            "collaborative_graph_heads",
            "templates",
            "graph_executions",
            "artifact_objects",
            "graph_execution_nodes",
            "invocation_cache_entries",
            "materialized_node_outputs",
        )
    ]


@pytest.mark.asyncio
async def test_apply_fence_fails_closed_on_unsupported_dialect(
    cutover_database: tuple[Database, InstalledPluginRelease],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )
    monkeypatch.setattr(database.engine.dialect, "name", "oracle")

    with pytest.raises(
        SystemCutoverError,
        match=r"database dialect 'oracle' is unsupported",
    ):
        await service.execute(
            SystemCutoverCommand(
                mode="apply",
                baseline=_baseline(release),
                rollback_unit=_rollback_unit(),
                expected_precondition_token=audit.precondition_token,
            )
        )

    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )
    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.invocation_cache_entries)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_apply_fence_serializes_queued_execution_insert_before_drain_check(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )

    blocker = database.sessions()
    async with blocker:
        await blocker.execute(text("BEGIN IMMEDIATE"))
        await blocker.execute(
            schema.graph_executions.insert().values(
                workspace_id=WORKSPACE_ID,
                execution_id=QUEUED_EXECUTION_ID,
                graph_id=GRAPH_ID,
                graph_revision=7,
                status="queued",
                scope="all",
                submitted_request=_run_request(),
                created_at=NOW,
            )
        )
        release_lock = asyncio.create_task(blocker.commit())
        try:
            with pytest.raises(
                SystemCutoverBlockedError,
                match="drained execution queue",
            ):
                await service.execute(
                    SystemCutoverCommand(
                        mode="apply",
                        baseline=_baseline(release),
                        rollback_unit=_rollback_unit(),
                        expected_precondition_token=audit.precondition_token,
                    )
                )
        finally:
            await release_lock

    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )
    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.invocation_cache_entries)
            )
            == 1
        )
        assert (
            await connection.scalar(
                select(schema.graph_executions.c.status).where(
                    schema.graph_executions.c.execution_id == QUEUED_EXECUTION_ID
                )
            )
            == "queued"
        )


@pytest.mark.asyncio
async def test_sqlite_apply_waits_for_write_reservation_before_auditing(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )

    blocker = database.sessions()
    async with blocker:
        await blocker.execute(text("BEGIN IMMEDIATE"))
        started = time.monotonic()
        with pytest.raises(OperationalError, match="database is locked"):
            await service.execute(
                SystemCutoverCommand(
                    mode="apply",
                    baseline=_baseline(release),
                    rollback_unit=_rollback_unit(),
                    expected_precondition_token=audit.precondition_token,
                )
            )
        elapsed = time.monotonic() - started
        await blocker.rollback()

    # A deferred transaction would have audited and finished immediately; the
    # apply waited the full busy timeout on the database write reservation.
    assert elapsed >= 4


@pytest.mark.asyncio
async def test_apply_cas_rejects_document_changed_after_audit_and_rolls_back(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TRIGGER cas_tamper_audit BEFORE UPDATE ON saved_graphs "
                "BEGIN UPDATE saved_graph_revisions "
                "SET document = '{\"nodes\": []}'; END"
            )
        )

    with pytest.raises(
        SystemCutoverPreconditionError,
        match="saved_graph_revisions row .* changed after audit",
    ):
        await service.execute(
            SystemCutoverCommand(
                mode="apply",
                baseline=_baseline(release),
                rollback_unit=_rollback_unit(),
                expected_precondition_token=audit.precondition_token,
            )
        )

    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )
    assert await _raw_document(
        database, schema.saved_graph_revisions, "document"
    ) == _graph_document().model_dump(mode="json")
    assert await _raw_document(
        database, schema.collaborative_graph_heads, "document"
    ) == _graph_document().model_dump(mode="json")
    assert await _raw_document(database, schema.templates, "snapshot_document") == (
        _graph_document().model_dump(mode="json")
    )
    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.invocation_cache_entries)
            )
            == 1
        )
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.materialized_node_outputs)
            )
            == 1
        )
        provenance = await connection.scalar(
            select(type_coerce(schema.artifact_objects.c.metadata, JSON))
        )
        assert provenance == {
            "plugin_release": {
                "scope": "system",
                "slug": "builtin.text",
                "revision": 0,
            }
        }


@pytest.mark.asyncio
async def test_apply_cas_rejects_deleted_audited_row_and_rolls_back(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, release = cutover_database
    service = SystemBaselineCutoverService(database.sessions)
    audit = await service.execute(
        SystemCutoverCommand(
            mode="dry-run",
            baseline=_baseline(release),
            rollback_unit=_rollback_unit(),
        )
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TRIGGER cas_delete_audited BEFORE UPDATE ON saved_graphs "
                f"BEGIN DELETE FROM templates WHERE id = '{TEMPLATE_ID.hex}'; END"
            )
        )

    with pytest.raises(
        SystemCutoverPreconditionError,
        match="templates row .* changed after audit",
    ):
        await service.execute(
            SystemCutoverCommand(
                mode="apply",
                baseline=_baseline(release),
                rollback_unit=_rollback_unit(),
                expected_precondition_token=audit.precondition_token,
            )
        )

    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(select(func.count()).select_from(schema.templates))
            == 1
        )
    assert await _raw_document(database, schema.saved_graphs, "document") == (
        _graph_document().model_dump(mode="json")
    )
    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.invocation_cache_entries)
            )
            == 1
        )
        assert (
            await connection.scalar(
                select(func.count()).select_from(schema.materialized_node_outputs)
            )
            == 1
        )


async def test_system_revocation_fence_blocks_queue_insert_until_commit(
    cutover_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, release = cutover_database
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    drain_checked = asyncio.Event()
    resume = asyncio.Event()
    original_add = SqlPluginReleaseRepository.add_revocation

    async def pause_before_revocation_insert(
        repository: SqlPluginReleaseRepository,
        revocation: PluginReleaseRevocation,
    ) -> PluginReleaseRevocation:
        drain_checked.set()
        await resume.wait()
        return await original_add(repository, revocation)

    monkeypatch.setattr(
        SqlPluginReleaseRepository, "add_revocation", pause_before_revocation_insert
    )
    pending = asyncio.create_task(
        service.revoke_system(
            slug=release.slug,
            revision=release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=PlatformPluginActor("cli:security-response"),
        )
    )
    try:
        await asyncio.wait_for(drain_checked.wait(), timeout=10)
        async with database.engine.connect() as connection:
            await connection.execute(text("PRAGMA busy_timeout=0"))
            with pytest.raises(OperationalError, match="database is locked"):
                await connection.execute(
                    schema.graph_executions.insert().values(
                        workspace_id=WORKSPACE_ID,
                        execution_id=QUEUED_EXECUTION_ID,
                        graph_id=GRAPH_ID,
                        graph_revision=7,
                        status="queued",
                        scope="all",
                        submitted_request=_run_request(),
                        created_at=NOW,
                    )
                )
            await connection.rollback()
        resume.set()
        revoked = await pending
        assert revoked.installation_id == release.installation_id
        async with database.engine.begin() as connection:
            await connection.execute(
                schema.graph_executions.insert().values(
                    workspace_id=WORKSPACE_ID,
                    execution_id=QUEUED_EXECUTION_ID,
                    graph_id=GRAPH_ID,
                    graph_revision=7,
                    status="queued",
                    scope="all",
                    submitted_request=_run_request(),
                    created_at=NOW,
                )
            )
        assert (
            await service.get_system_revocation(
                slug=release.slug,
                revision=release.revision,
            )
            == revoked
        )
    finally:
        resume.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_system_revocation_waits_for_queue_insert_before_checking_drain(
    cutover_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
) -> None:
    database, release = cutover_database
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    async with database.sessions() as blocker:
        await blocker.execute(text("BEGIN IMMEDIATE"))
        await blocker.execute(
            schema.graph_executions.insert().values(
                workspace_id=WORKSPACE_ID,
                execution_id=QUEUED_EXECUTION_ID,
                graph_id=GRAPH_ID,
                graph_revision=7,
                status="queued",
                scope="all",
                submitted_request=_run_request(),
                created_at=NOW,
            )
        )
        commit = asyncio.create_task(blocker.commit())
        try:
            with pytest.raises(
                PluginReleaseRevocationError, match="drained execution queue"
            ):
                await service.revoke_system(
                    slug=release.slug,
                    revision=release.revision,
                    reason=PluginReleaseRevocationReason.SECURITY,
                    platform_actor=PlatformPluginActor("cli:security-response"),
                )
        finally:
            await commit
    assert (
        await service.get_system_revocation(
            slug=release.slug, revision=release.revision
        )
        is None
    )


async def test_system_revocation_fails_closed_without_supported_database_fence(
    cutover_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, release = cutover_database
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    monkeypatch.setattr(database.engine.dialect, "name", "oracle")
    with pytest.raises(
        PluginReleaseRevocationError, match="database dialect 'oracle' is unsupported"
    ):
        await service.revoke_system(
            slug=release.slug,
            revision=release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=PlatformPluginActor("cli:security-response"),
        )
    assert (
        await service.get_system_revocation(
            slug=release.slug, revision=release.revision
        )
        is None
    )

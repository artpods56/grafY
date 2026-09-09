from collections.abc import Collection
from datetime import UTC, datetime
from itertools import batched
from typing import cast, override
from uuid import UUID
from sqlalchemy import (
    and_,
    case,
    delete,
    func,
    insert,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.errors import (
    CollaborationActiveExecutionError,
    NotFoundError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.execution_history import (
    GraphExecution,
    TransientExecution,
    GraphExecutionCursor,
    GraphExecutionDetail,
    GraphExecutionListItem,
    GraphExecutionNodeResult,
    GraphExecutionPage,
    GraphExecutionStatus,
)
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.ports.invocation_cache import InvocationCacheRepositoryPort
from grafy_core.ports.execution_history import (
    GraphExecutionHistoryRepositoryPort,
)
from grafy_core.ports.materialized_outputs import (
    MaterializedNodeOutputsRepositoryPort,
)
from grafy_persistence import schema
from grafy_persistence.orm import GraphExecutionRecord


_ACTIVE_EXECUTION_STATUSES = ("queued", "running", "cancelling")


class SqlInvocationCacheRepository(InvocationCacheRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        return await self._session.get(
            InvocationCacheEntry,
            (workspace_id, key_sha256),
        )

    @override
    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        table = schema.invocation_cache_entries
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            insert_statement = sqlite_insert(table)
        elif dialect_name == "postgresql":
            insert_statement = postgresql_insert(table)
        else:
            raise NotImplementedError(
                "Invocation cache publication requires SQLite or PostgreSQL; "
                f"received dialect {dialect_name!r}"
            )

        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                insert_statement.values(
                    key_sha256=entry.key_sha256,
                    workspace_id=entry.workspace_id,
                    generation=entry.generation,
                    outputs=entry.outputs,
                    created_at=entry.created_at,
                ).on_conflict_do_nothing(
                    index_elements=(table.c.workspace_id, table.c.key_sha256),
                )
            ),
        )
        return result.rowcount == 1

    @override
    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        table = schema.invocation_cache_entries
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(table).where(
                    table.c.workspace_id == workspace_id,
                    table.c.key_sha256 == key_sha256,
                    table.c.generation == generation,
                )
            ),
        )
        return result.rowcount == 1


class SqlMaterializedNodeOutputsRepository(
    MaterializedNodeOutputsRepositoryPort,
):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def upsert(self, value: MaterializedNodeOutputs) -> None:
        table = schema.materialized_node_outputs
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            insert_statement = sqlite_insert(table)
        elif dialect_name == "postgresql":
            insert_statement = postgresql_insert(table)
        else:
            raise NotImplementedError(
                "Materialized output upsert requires SQLite or PostgreSQL; "
                f"received dialect {dialect_name!r}"
            )

        insert_statement = insert_statement.values(
            workspace_id=value.workspace_id,
            graph_id=value.graph_id,
            graph_revision=value.graph_revision,
            node_id=value.node_id,
            workflow_run_id=value.workflow_run_id,
            outputs=value.outputs,
            materialized_at=value.materialized_at,
        )
        await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=(
                    table.c.workspace_id,
                    table.c.graph_id,
                    table.c.graph_revision,
                    table.c.node_id,
                ),
                set_={
                    "workflow_run_id": insert_statement.excluded.workflow_run_id,
                    "outputs": insert_statement.excluded.outputs,
                    "materialized_at": insert_statement.excluded.materialized_at,
                },
            )
        )

    @override
    async def get(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        node_id: str,
    ) -> MaterializedNodeOutputs | None:
        return await self._session.get(
            MaterializedNodeOutputs,
            (workspace_id, graph_id, graph_revision, node_id),
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> list[MaterializedNodeOutputs]:
        result = await self._session.scalars(
            select(MaterializedNodeOutputs)
            .where(
                schema.materialized_node_outputs.c.graph_id == graph_id,
                schema.materialized_node_outputs.c.graph_revision == graph_revision,
                schema.materialized_node_outputs.c.workspace_id == workspace_id,
            )
            .order_by(schema.materialized_node_outputs.c.node_id.asc())
        )
        return list(result)


class SqlGraphExecutionHistoryRepository(
    GraphExecutionHistoryRepositoryPort,
):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add_transient(self, execution: TransientExecution) -> None:
        await self._session.execute(
            insert(schema.transient_executions).values(
                execution_id=execution.execution_id,
                workspace_id=execution.workspace_id,
                owner_id=execution.owner_id,
                created_at=execution.created_at,
            )
        )

    @override
    async def remove_transient(self, execution_id: UUID, owner_id: UUID) -> None:
        table = schema.transient_executions
        await self._session.execute(
            delete(table).where(
                table.c.execution_id == execution_id, table.c.owner_id == owner_id
            )
        )

    @override
    async def list_transient(self) -> tuple[TransientExecution, ...]:
        table = schema.transient_executions
        rows = await self._session.execute(
            select(table).order_by(table.c.created_at, table.c.execution_id)
        )
        return tuple(
            TransientExecution(
                execution_id=row.execution_id,
                workspace_id=row.workspace_id,
                owner_id=row.owner_id,
                created_at=row.created_at,
            )
            for row in rows
        )

    @override
    async def clear_transient(self) -> None:
        await self._session.execute(delete(schema.transient_executions))

    @override
    async def add(self, execution: GraphExecution) -> None:
        table = schema.graph_executions
        revision_exists = await self._session.scalar(
            select(schema.saved_graph_revisions.c.graph_id).where(
                schema.saved_graph_revisions.c.workspace_id == execution.workspace_id,
                schema.saved_graph_revisions.c.graph_id == execution.graph_id,
                schema.saved_graph_revisions.c.revision == execution.graph_revision,
            )
        )
        if revision_exists is None:
            raise NotFoundError(
                "Saved graph revision",
                f"{execution.graph_id}/r{execution.graph_revision}",
            )
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(table).values(
                        execution_id=execution.execution_id,
                        workspace_id=execution.workspace_id,
                        graph_id=execution.graph_id,
                        graph_revision=execution.graph_revision,
                        status=execution.status,
                        scope=execution.scope,
                        submitted_request=execution.submitted_request,
                        idempotency_key=execution.idempotency_key,
                        submitted_by_actor_id=execution.submitted_by_actor_id,
                        workflow_run_id=execution.workflow_run_id,
                        error=execution.error,
                        created_at=execution.created_at,
                        started_at=execution.started_at,
                        finished_at=execution.finished_at,
                    )
                )
                if execution.requested_node_ids:
                    await self._session.execute(
                        insert(schema.graph_execution_nodes),
                        [
                            {
                                "workspace_id": execution.workspace_id,
                                "execution_id": execution.execution_id,
                                "node_id": node_id,
                                "position": position,
                            }
                            for position, node_id in enumerate(
                                execution.requested_node_ids
                            )
                        ],
                    )
        except IntegrityError as exc:
            await self._session.rollback()
            active_execution_id = await self.find_active_execution_id(
                execution.workspace_id,
                execution.graph_id,
            )
            if active_execution_id is not None:
                raise CollaborationActiveExecutionError(
                    workspace_id=execution.workspace_id,
                    graph_id=execution.graph_id,
                    execution_id=active_execution_id,
                ) from exc
            raise ObjectAlreadyExistsError(
                f"Graph execution already exists: {execution.execution_id}"
            ) from exc

    @override
    async def update(self, execution: GraphExecution) -> None:
        current_record = await self._session.scalar(
            select(GraphExecutionRecord).where(
                schema.graph_executions.c.workspace_id == execution.workspace_id,
                schema.graph_executions.c.execution_id == execution.execution_id,
            )
        )
        if current_record is None:
            raise NotFoundError("Graph execution", str(execution.execution_id))
        (current,) = await self._hydrate_executions((current_record,))
        if (
            current.graph_id != execution.graph_id
            or current.graph_revision != execution.graph_revision
            or current.scope != execution.scope
            or current.requested_node_ids != execution.requested_node_ids
            or current.submitted_request != execution.submitted_request
            or current.idempotency_key != execution.idempotency_key
            or current.submitted_by_actor_id != execution.submitted_by_actor_id
            or current.created_at != execution.created_at
        ):
            raise ValueError(
                f"Graph execution {execution.execution_id} identity and request "
                "fields are immutable"
            )

        await self._session.execute(
            update(schema.graph_executions)
            .where(
                schema.graph_executions.c.workspace_id == execution.workspace_id,
                schema.graph_executions.c.execution_id == execution.execution_id,
            )
            .values(
                status=execution.status,
                workflow_run_id=execution.workflow_run_id,
                error=execution.error,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
            )
        )

    @override
    async def add_node_result(self, result: GraphExecutionNodeResult) -> None:
        execution_exists = await self._session.scalar(
            select(schema.graph_executions.c.execution_id).where(
                schema.graph_executions.c.workspace_id == result.workspace_id,
                schema.graph_executions.c.execution_id == result.execution_id,
            )
        )
        if execution_exists is None:
            raise NotFoundError("Graph execution", str(result.execution_id))
        nodes = schema.graph_execution_nodes
        requested = await self._session.execute(
            select(nodes.c.result_status).where(
                nodes.c.workspace_id == result.workspace_id,
                nodes.c.execution_id == result.execution_id,
                nodes.c.node_id == result.node_id,
            )
        )
        requested_row = requested.one_or_none()
        if requested_row is None:
            raise ValueError(
                f"Graph execution {result.execution_id} did not request node "
                f"{result.node_id!r}"
            )
        if requested_row.result_status is not None:
            raise ObjectAlreadyExistsError(
                "Graph execution node result already exists: "
                f"{result.execution_id}/{result.node_id}"
            )
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    update(nodes)
                    .where(
                        nodes.c.workspace_id == result.workspace_id,
                        nodes.c.execution_id == result.execution_id,
                        nodes.c.node_id == result.node_id,
                    )
                    .values(
                        result_status=result.status,
                        result_position=result.position,
                        outputs=result.outputs,
                        artifact_count=result.artifact_count,
                        error=result.error,
                        diagnostics=result.diagnostics,
                        completed_at=result.completed_at,
                    )
                )
        except IntegrityError as exc:
            await self._session.rollback()
            raise ObjectAlreadyExistsError(
                "Graph execution node result position already exists: "
                f"{result.execution_id}/{result.position}"
            ) from exc

    @override
    async def find_active_execution_id(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> UUID | None:
        return await self._session.scalar(
            select(schema.graph_executions.c.execution_id)
            .where(
                schema.graph_executions.c.workspace_id == workspace_id,
                schema.graph_executions.c.graph_id == graph_id,
                schema.graph_executions.c.status.in_(_ACTIVE_EXECUTION_STATUSES),
            )
            .order_by(
                schema.graph_executions.c.created_at.asc(),
                schema.graph_executions.c.execution_id.asc(),
            )
            .limit(1)
        )

    @override
    async def get(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> GraphExecutionDetail | None:
        record = await self._session.scalar(
            select(GraphExecutionRecord).where(
                schema.graph_executions.c.workspace_id == workspace_id,
                schema.graph_executions.c.execution_id == execution_id,
            )
        )
        if record is None:
            return None
        (execution,) = await self._hydrate_executions((record,))
        nodes = schema.graph_execution_nodes
        result_rows = (
            await self._session.execute(
                select(
                    nodes.c.node_id,
                    nodes.c.result_position,
                    nodes.c.result_status,
                    nodes.c.outputs,
                    nodes.c.error,
                    nodes.c.diagnostics,
                    nodes.c.completed_at,
                )
                .where(
                    nodes.c.workspace_id == workspace_id,
                    nodes.c.execution_id == execution_id,
                    nodes.c.result_status.is_not(None),
                )
                .order_by(nodes.c.result_position.asc(), nodes.c.node_id.asc())
            )
        ).all()
        results = tuple(
            GraphExecutionNodeResult(
                workspace_id=workspace_id,
                execution_id=execution_id,
                node_id=row.node_id,
                position=row.result_position,
                status=row.result_status,
                outputs=row.outputs,
                error=row.error,
                diagnostics=row.diagnostics,
                completed_at=row.completed_at.replace(tzinfo=UTC),
            )
            for row in result_rows
        )
        return GraphExecutionDetail(
            execution=execution,
            node_results=results,
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        limit: int,
        cursor: GraphExecutionCursor | None = None,
        graph_revision: int | None = None,
        status: GraphExecutionStatus | None = None,
        node_id: str | None = None,
    ) -> GraphExecutionPage:
        if limit < 1:
            raise ValueError("Graph execution page limit must be at least 1")
        if graph_revision is not None and graph_revision < 1:
            raise ValueError("Graph execution revision filter must be at least 1")
        normalized_node_id = None
        if node_id is not None:
            normalized_node_id = node_id.strip()
            if normalized_node_id == "":
                raise ValueError("Graph execution node filter must not be blank")

        executions = schema.graph_executions
        nodes = schema.graph_execution_nodes
        counts = (
            select(
                nodes.c.workspace_id,
                nodes.c.execution_id,
                func.sum(
                    case(
                        (nodes.c.result_status.is_not(None), 1),
                        else_=0,
                    )
                ).label("node_count"),
                func.coalesce(func.sum(nodes.c.artifact_count), 0).label(
                    "artifact_count"
                ),
            )
            .group_by(
                nodes.c.workspace_id,
                nodes.c.execution_id,
            )
            .subquery()
        )
        statement = (
            select(
                GraphExecutionRecord,
                func.coalesce(counts.c.node_count, 0),
                func.coalesce(counts.c.artifact_count, 0),
            )
            .outerjoin(
                counts,
                and_(
                    counts.c.workspace_id == executions.c.workspace_id,
                    counts.c.execution_id == executions.c.execution_id,
                ),
            )
            .where(
                executions.c.workspace_id == workspace_id,
                executions.c.graph_id == graph_id,
            )
        )
        if graph_revision is not None:
            statement = statement.where(executions.c.graph_revision == graph_revision)
        if status is not None:
            statement = statement.where(executions.c.status == status)
        if normalized_node_id is not None:
            statement = statement.where(
                select(1)
                .where(
                    nodes.c.execution_id == executions.c.execution_id,
                    nodes.c.workspace_id == workspace_id,
                    nodes.c.node_id == normalized_node_id,
                )
                .exists()
            )
        if cursor is not None:
            statement = statement.where(
                or_(
                    executions.c.created_at < cursor.created_at,
                    (
                        (executions.c.created_at == cursor.created_at)
                        & (executions.c.execution_id < cursor.execution_id)
                    ),
                )
            )
        statement = statement.order_by(
            executions.c.created_at.desc(),
            executions.c.execution_id.desc(),
        ).limit(limit + 1)
        rows = list((await self._session.execute(statement)).all())
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page_executions = await self._hydrate_executions(
            tuple(row[0] for row in page_rows)
        )
        items = tuple(
            GraphExecutionListItem(
                execution=execution,
                node_count=int(row[1]),
                artifact_count=int(row[2]),
            )
            for execution, row in zip(page_executions, page_rows, strict=True)
        )
        next_cursor = None
        if has_more and items:
            last = items[-1].execution
            next_cursor = GraphExecutionCursor(
                created_at=last.created_at,
                execution_id=last.execution_id,
            )
        return GraphExecutionPage(items=items, next_cursor=next_cursor)

    @override
    async def list_queued(self) -> tuple[GraphExecution, ...]:
        records = tuple(
            await self._session.scalars(
                select(GraphExecutionRecord)
                .where(schema.graph_executions.c.status == "queued")
                .order_by(
                    schema.graph_executions.c.created_at.asc(),
                    schema.graph_executions.c.execution_id.asc(),
                )
            )
        )
        return await self._hydrate_executions(records)

    @override
    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> GraphExecution | None:
        record = await self._session.scalar(
            select(GraphExecutionRecord).where(
                schema.graph_executions.c.workspace_id == workspace_id,
                schema.graph_executions.c.idempotency_key == idempotency_key,
            )
        )
        if record is None:
            return None
        (execution,) = await self._hydrate_executions((record,))
        return execution

    @override
    async def claim_queued(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        *,
        started_at: datetime,
    ) -> bool:
        if started_at.tzinfo is None:
            raise ValueError("Graph execution start timestamp must be timezone-aware")
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                update(schema.graph_executions)
                .where(
                    schema.graph_executions.c.workspace_id == workspace_id,
                    schema.graph_executions.c.execution_id == execution_id,
                    schema.graph_executions.c.status == "queued",
                )
                .values(status="running", started_at=started_at)
            ),
        )
        return result.rowcount == 1

    @override
    async def interrupt_started(
        self,
        *,
        finished_at: datetime,
        error: str,
    ) -> tuple[GraphExecution, ...]:
        if finished_at.tzinfo is None:
            raise ValueError(
                "Graph execution interruption timestamp must be timezone-aware"
            )
        records = tuple(
            await self._session.scalars(
                select(GraphExecutionRecord).where(
                    schema.graph_executions.c.status.in_(("running", "cancelling"))
                )
            )
        )
        interrupted = await self._hydrate_executions(records)
        if interrupted:
            await self._session.execute(
                update(schema.graph_executions)
                .where(
                    schema.graph_executions.c.execution_id.in_(
                        execution.execution_id for execution in interrupted
                    )
                )
                .values(
                    status="failed",
                    finished_at=finished_at,
                    error=error,
                )
            )
        return interrupted

    async def _hydrate_executions(
        self,
        records: Collection[GraphExecutionRecord],
    ) -> tuple[GraphExecution, ...]:
        nodes = schema.graph_execution_nodes
        requested: dict[tuple[UUID, UUID], list[str]] = {}
        # Each identity binds two values; bounded batches also support SQLite's
        # older 999-variable statement limit during large queue recovery.
        for batch in batched(records, 400):
            identities = [
                (record.workspace_id, record.execution_id) for record in batch
            ]
            rows = await self._session.execute(
                select(nodes.c.workspace_id, nodes.c.execution_id, nodes.c.node_id)
                .where(
                    tuple_(nodes.c.workspace_id, nodes.c.execution_id).in_(identities)
                )
                .order_by(nodes.c.workspace_id, nodes.c.execution_id, nodes.c.position)
            )
            for workspace_id, execution_id, node_id in rows:
                requested.setdefault((workspace_id, execution_id), []).append(node_id)
        return tuple(
            record.to_domain(
                tuple(requested.get((record.workspace_id, record.execution_id), ()))
            )
            for record in records
        )

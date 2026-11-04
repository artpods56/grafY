"""SQL adapters for Runs and the persistent result store (ADR 0020, issue #195).

Both repositories are built on one supplied ``AsyncSession`` and speak Core SQL.
Every statement carries ``workspace_id`` in its ``WHERE`` (or in the composite key
it reads by), so a row of another Workspace is indistinguishable from one that was
never there and two Workspaces can never share a fingerprint's result.

The result row is append-once: ``put_result_if_absent`` inserts on conflict do
nothing and then reads the row, so a fingerprint that already has a result keeps
the original, byte for byte. The instance pointer is the only mutable record of
an instance: a success moves the result pointer and clears the failure; a failure
replaces the failure and preserves the previous result.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast, override
from uuid import UUID

from sqlalchemy import String, insert, select, update
from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.domain.artifact_outputs import (
    ArtifactOutputValue,
)
from grafy_core.domain.runs import (
    Run,
    RunStatus,
    RunTarget,
)
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import (
    FailureRecord,
    InstancePointer,
    StoredResult,
)
from grafy_core.ports.runs import (
    ResultStoreRepositoryPort,
    RunRepositoryPort,
)
from grafy_persistence import schema


def instance_digest(instance: InstanceKey) -> str:
    """SHA-256 of the canonical JSON of the *full* instance key.

    The JSON itself cannot serve as a portable PostgreSQL primary key, so its
    digest keys the pointer row; the key's coordinates are stored beside it and
    read back as the original ``InstanceKey``. Two keys differing in any field,
    including ``call_path`` or ``map_index``, digest differently.
    """
    canonical = json.dumps(
        {
            "project_id": instance.project_id,
            "graph_id": instance.graph_id,
            "call_path": list(instance.call_path),
            "node_id": instance.node_id,
            "map_index": instance.map_index,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _targets_to_storage(targets: tuple[RunTarget, ...]) -> list[dict[str, object]]:
    return [
        {"node_id": target.node_id, "call_path": list(target.call_path)}
        for target in targets
    ]


class _StoredRunTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str
    call_path: list[str]


_RUN_TARGETS = TypeAdapter(list[_StoredRunTarget])
_CALL_PATH = TypeAdapter(list[str])


def _targets_from_storage(value: object) -> tuple[RunTarget, ...]:
    return tuple(
        RunTarget(node_id=target.node_id, call_path=tuple(target.call_path))
        for target in _RUN_TARGETS.validate_python(value, strict=True)
    )


def _pointer_key_from_row(row) -> InstanceKey:
    call_path = row["call_path"]
    return InstanceKey(
        project_id=str(cast(UUID, row["project_id"])),
        graph_id=cast(str, row["graph_id"]),
        call_path=tuple(_CALL_PATH.validate_python(call_path, strict=True)),
        node_id=cast(str, row["node_id"]),
        map_index=None if row["map_index"] is None else int(row["map_index"]),
    )


def _pointer_from_row(row) -> InstancePointer:
    failure_fingerprint = row["failure_fingerprint"]
    return InstancePointer(
        last_result_fingerprint=row["last_result_fingerprint"],
        last_failure=(
            None
            if failure_fingerprint is None
            else FailureRecord(
                fingerprint=cast(str, failure_fingerprint),
                message=cast(str, row["failure_message"]),
                failed_at=row["failed_at"],
            )
        ),
    )


def _run_from_row(row) -> Run:
    return Run(
        workspace_id=cast(UUID, row["workspace_id"]),
        project_id=cast(UUID, row["project_id"]),
        graph_id=cast(str, row["graph_id"]),
        targets=_targets_from_storage(row["targets"]),
        started_by_user_id=row["started_by_user_id"],
        id=cast(UUID, row["id"]),
        status=RunStatus(cast(str, row["status"])),
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        error=row["error"],
    )


class SqlRunRepository(RunRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, run: Run) -> None:
        await self._session.execute(
            insert(schema.project_runs).values(
                id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                graph_id=run.graph_id,
                targets=_targets_to_storage(run.targets),
                started_by_user_id=run.started_by_user_id,
                status=run.status.value,
                created_at=run.created_at,
                finished_at=run.finished_at,
                error=run.error,
            )
        )

    @override
    async def get(
        self,
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
    ) -> Run | None:
        table = schema.project_runs
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                        table.c.id == run_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _run_from_row(row)

    @override
    async def save(self, run: Run) -> None:
        # A transition writes status, finish stamp and error, and nothing else.
        # The WHERE is scoped to the Run's full identity, so a Run that is not
        # this Workspace's and this Project's row is silently not this row's.
        await self._session.execute(
            update(schema.project_runs)
            .where(
                schema.project_runs.c.workspace_id == run.workspace_id,
                schema.project_runs.c.project_id == run.project_id,
                schema.project_runs.c.id == run.id,
            )
            .values(
                status=run.status.value, finished_at=run.finished_at, error=run.error
            )
        )

    @override
    async def list_for_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Run]:
        table = schema.project_runs
        statement = (
            select(table)
            .where(
                table.c.workspace_id == workspace_id,
                table.c.project_id == project_id,
            )
            .order_by(table.c.created_at.desc(), table.c.id.asc())
            .limit(limit)
        )
        if active_only:
            statement = statement.where(table.c.status == RunStatus.RUNNING.value)
        rows = (await self._session.execute(statement)).mappings().all()
        return [_run_from_row(row) for row in rows]

    @override
    async def interrupt_unfinished(self, *, at: datetime, error: str) -> list[Run]:
        table = schema.project_runs
        statement = select(table).where(table.c.status == RunStatus.RUNNING.value)
        if self._session.get_bind().dialect.name == "postgresql":
            # Lock the rows a concurrent owner might be finishing; the API holds
            # the single-owner lease at startup, so this only closes the race
            # against a transaction that committed but was not yet observed.
            statement = statement.with_for_update()
        rows = (await self._session.execute(statement)).mappings().all()
        runs = [_run_from_row(row) for row in rows]
        if not runs:
            return []
        await self._session.execute(
            update(table)
            .where(table.c.id.in_([run.id for run in runs]))
            .where(table.c.status == RunStatus.RUNNING.value)
            .values(status=RunStatus.INTERRUPTED.value, finished_at=at, error=error)
        )
        for run in runs:
            run.status = RunStatus.INTERRUPTED
            run.finished_at = at
            run.error = error
        return runs


class SqlResultStoreRepository(ResultStoreRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def artifact_is_referenced(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> bool:
        # Conservative prefilter in SQL: a stored outputs payload that cannot
        # even contain the identity as text is skipped. The decision is then made
        # on the typed refs, so artifact ids appearing only in free metadata
        # text are not references.
        needle = f"%{artifact_id}%"
        rows = (
            await self._session.execute(
                select(schema.node_results.c.outputs).where(
                    schema.node_results.c.workspace_id == workspace_id,
                    schema.node_results.c.outputs.cast(String).like(needle),
                )
            )
        ).all()
        return any(
            _outputs_reference(
                cast(dict[str, ArtifactOutputValue], outputs), artifact_id
            )
            for (outputs,) in rows
        )

    @override
    async def get_result(
        self,
        workspace_id: UUID,
        fingerprint: str,
    ) -> StoredResult | None:
        table = schema.node_results
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.fingerprint == fingerprint,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _result_from_row(row)

    @override
    async def put_result_if_absent(
        self,
        workspace_id: UUID,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
        *,
        created_at: datetime,
    ) -> StoredResult:
        table = schema.node_results
        statement = _dialect_insert(self._session, table).values(
            workspace_id=workspace_id,
            fingerprint=fingerprint,
            outputs=dict(outputs),
            created_at=created_at,
        )
        await self._session.execute(statement.on_conflict_do_nothing())
        # Read the row back whatever happened: on a conflict the insert was a
        # no-op and the original row, unchanged, is the answer.
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.fingerprint == fingerprint,
                    )
                )
            )
            .mappings()
            .one()
        )
        return _result_from_row(row)

    @override
    async def get_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
    ) -> InstancePointer | None:
        table = schema.instance_pointers
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.instance_digest == instance_digest(instance),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _pointer_from_row(row)

    @override
    async def list_pointers(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> Mapping[InstanceKey, InstancePointer]:
        table = schema.instance_pointers
        rows = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                    )
                )
            )
            .mappings()
            .all()
        )
        return {_pointer_key_from_row(row): _pointer_from_row(row) for row in rows}

    @override
    async def set_success_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        fingerprint: str,
    ) -> None:
        statement = _pointer_insert(self._session, workspace_id, instance).values(
            last_result_fingerprint=fingerprint,
            failure_fingerprint=None,
            failure_message=None,
            failed_at=None,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=(
                    schema.instance_pointers.c.workspace_id,
                    schema.instance_pointers.c.instance_digest,
                ),
                set_={
                    "last_result_fingerprint": statement.excluded.last_result_fingerprint,
                    "failure_fingerprint": None,
                    "failure_message": None,
                    "failed_at": None,
                },
            )
        )

    @override
    async def set_failure_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        statement = _pointer_insert(self._session, workspace_id, instance).values(
            last_result_fingerprint=None,
            failure_fingerprint=failure.fingerprint,
            failure_message=failure.message,
            failed_at=failure.failed_at,
        )
        # The previous result pointer is deliberately not in ``set_``: a failure
        # replaces the failure and keeps the instance's last result.
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=(
                    schema.instance_pointers.c.workspace_id,
                    schema.instance_pointers.c.instance_digest,
                ),
                set_={
                    "failure_fingerprint": statement.excluded.failure_fingerprint,
                    "failure_message": statement.excluded.failure_message,
                    "failed_at": statement.excluded.failed_at,
                },
            )
        )


def _pointer_insert(
    session: AsyncSession,
    workspace_id: UUID,
    instance: InstanceKey,
):
    statement = _dialect_insert(session, schema.instance_pointers).values(
        workspace_id=workspace_id,
        instance_digest=instance_digest(instance),
        project_id=UUID(instance.project_id),
        graph_id=instance.graph_id,
        call_path=list(instance.call_path),
        node_id=instance.node_id,
        map_index=instance.map_index,
    )
    return statement


def _result_from_row(row) -> StoredResult:
    return StoredResult(
        fingerprint=cast(str, row["fingerprint"]),
        outputs=cast(dict[str, ArtifactOutputValue], row["outputs"]),
        created_at=row["created_at"],
    )


def _outputs_reference(
    outputs: Mapping[str, ArtifactOutputValue], artifact_id: UUID
) -> bool:
    for value in outputs.values():
        if isinstance(value, ArtifactRefSequence):
            if any(ref.artifact_id == artifact_id for ref in value.item_refs):
                return True
        elif isinstance(value, ArtifactRef) and value.artifact_id == artifact_id:
            return True
    return False


def _dialect_insert(session: AsyncSession, table):
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        raise NotImplementedError(
            f"Run persistence requires SQLite or PostgreSQL; got {dialect_name!r}"
        )
    return dialect_insert(table)


__all__ = ["SqlResultStoreRepository", "SqlRunRepository", "instance_digest"]

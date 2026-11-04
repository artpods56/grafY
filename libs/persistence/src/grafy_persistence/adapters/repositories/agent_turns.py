"""SQL adapter for durable Agent turn receipts (ADR 0021, issue #202).

Every statement carries ``workspace_id``, so a receipt of another Workspace reads as
absent. The two admission rules are not coded here: they are the unique constraint and the
partial unique index on ``agent_turns``, and this adapter's job is to translate their
refusal into the two errors the application reasons about. Doing it the other way round —
reading first and writing only if the read was clear — is the version that loses under
concurrency, because two senders can both read "no turn is running".

A refused insert is not repaired inside the transaction. A refused admission means the
unit of work is rolled back, which is also what makes the receipt and the user message one
fact: whichever half is refused, neither is stored, and whatever the loser learns about the
winner's turn it learns from a fresh read afterwards.

``finish`` moves a receipt out of ``running`` with a conditional ``UPDATE``. Exactly one
caller can see one row changed, which is what makes a cancel, a model failure and startup
recovery mutually exclusive without anybody coordinating.
"""

from datetime import datetime
from typing import override
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.agent_turns import AgentTurn, AgentTurnStatus
from grafy_core.ports.agent_turns import (
    AgentTurnAlreadyAdmittedError,
    AgentTurnBusyError,
    AgentTurnRepositoryPort,
)
from grafy_persistence import schema

# The names the schema gives the two admission constraints. PostgreSQL reports the name in
# the driver error; SQLite reports the offending columns instead, and the client-turn
# constraint is the only one of the two that names ``client_turn_id``.
CLIENT_TURN_CONSTRAINT = "uq_agent_turns_conversation_client_turn"
ONE_RUNNING_CONSTRAINT = "uq_agent_turns_one_running_per_conversation"


def _turn_from_row(row: RowMapping) -> AgentTurn:
    return AgentTurn.model_validate(dict(row))


def _refused_admission(exc: IntegrityError) -> str:
    """Which admission rule a unique violation is, or ``""`` when it is neither.

    The whole error text is searched rather than one attribute because the two dialects
    disagree about where they put it: asyncpg names the constraint, SQLite names the
    columns of the index.
    """

    text = f"{type(exc.orig).__name__}: {exc.orig}"
    if CLIENT_TURN_CONSTRAINT in text or "client_turn_id" in text:
        return "client_turn_id"
    if ONE_RUNNING_CONSTRAINT in text:
        return "running"
    if "agent_turns.workspace_id, agent_turns.conversation_id" in text:
        # SQLite's wording for the partial index, which holds two columns and no more.
        return "running"
    if "agent_turns.id" in text:
        return ""
    # An unrecognised unique violation on this table would otherwise be reported as a busy
    # conversation, which is a lie about why the send failed.
    return ""


class SqlAgentTurnRepository(AgentTurnRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, turn: AgentTurn) -> None:
        table = schema.agent_turns
        try:
            await self._session.execute(insert(table).values(_turn_values(turn)))
        except IntegrityError as exc:
            reason = _refused_admission(exc)
            if reason == "client_turn_id":
                raise AgentTurnAlreadyAdmittedError(
                    f"Client turn {turn.client_turn_id} was already admitted for "
                    f"conversation {turn.conversation_id}"
                ) from exc
            if reason == "running":
                raise AgentTurnBusyError(turn.conversation_id) from exc
            raise

    @override
    async def get(self, workspace_id: UUID, turn_id: UUID) -> AgentTurn | None:
        table = schema.agent_turns
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id, table.c.id == turn_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _turn_from_row(row)

    @override
    async def get_by_client_turn_id(
        self, workspace_id: UUID, conversation_id: UUID, client_turn_id: str
    ) -> AgentTurn | None:
        table = schema.agent_turns
        row = (
            (
                await self._session.execute(
                    select(table)
                    .where(
                        table.c.workspace_id == workspace_id,
                        table.c.conversation_id == conversation_id,
                        table.c.client_turn_id == client_turn_id,
                    )
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _turn_from_row(row)

    @override
    async def running_for_conversation(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentTurn | None:
        # Advisory: this names the turn a refused send is waiting behind. The rule itself
        # is the partial unique index, so this read may be a turn stale and nothing
        # downstream decides permission from it.
        table = schema.agent_turns
        row = (
            (
                await self._session.execute(
                    select(table)
                    .where(
                        table.c.workspace_id == workspace_id,
                        table.c.conversation_id == conversation_id,
                        table.c.status == AgentTurnStatus.RUNNING.value,
                    )
                    .order_by(table.c.created_at.asc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _turn_from_row(row)

    @override
    async def list_for_conversation(
        self, workspace_id: UUID, conversation_id: UUID, *, limit: int | None = None
    ) -> list[AgentTurn]:
        table = schema.agent_turns
        statement = (
            select(table)
            .where(
                table.c.workspace_id == workspace_id,
                table.c.conversation_id == conversation_id,
            )
            .order_by(table.c.created_at.desc(), table.c.id.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).mappings().all()
        return [_turn_from_row(row) for row in rows]

    @override
    async def finish(
        self,
        workspace_id: UUID,
        turn_id: UUID,
        *,
        status: AgentTurnStatus,
        at: datetime,
        detail: str | None = None,
    ) -> AgentTurn | None:
        if not status.is_terminal:
            raise ValueError(f"{status} is not a terminal Agent turn status")
        table = schema.agent_turns
        claimed = await self._session.execute(
            update(table)
            .where(
                table.c.workspace_id == workspace_id,
                table.c.id == turn_id,
                table.c.status == AgentTurnStatus.RUNNING.value,
            )
            .values(status=status.value, finished_at=at, outcome_detail=detail)
        )
        if claimed.rowcount != 1:
            return None
        return await self.get(workspace_id, turn_id)

    @override
    async def list_running(self) -> list[AgentTurn]:
        table = schema.agent_turns
        statement = select(table).where(table.c.status == AgentTurnStatus.RUNNING.value)
        if self._session.get_bind().dialect.name == "postgresql":
            # Startup recovery. The previous owner is gone with its process, but a
            # transaction that committed and was not yet observed must not be skipped, and
            # a turn interrupted twice would write its outcome twice.
            statement = statement.with_for_update()
        rows = (
            (await self._session.execute(statement.order_by(table.c.created_at.asc())))
            .mappings()
            .all()
        )
        return [_turn_from_row(row) for row in rows]


def _turn_values(turn: AgentTurn) -> dict[str, object]:
    return {
        "id": turn.id,
        "workspace_id": turn.workspace_id,
        "project_id": turn.project_id,
        "graph_id": turn.graph_id,
        "agent_id": turn.agent_id,
        "conversation_id": turn.conversation_id,
        "client_turn_id": turn.client_turn_id,
        "requested_by_user_id": turn.requested_by_user_id,
        "status": turn.status.value,
        "request_digest": turn.request_digest,
        "user_message_sequence": turn.user_message_sequence,
        "instructions": turn.instructions,
        "model_source": turn.model_source,
        "model_name": turn.model_name,
        "outcome_detail": turn.outcome_detail,
        "created_at": turn.created_at,
        "finished_at": turn.finished_at,
    }

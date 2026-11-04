"""Runs: a demand for targets to become fresh (ADR 0020).

A Run is bookkeeping only. The results a Run causes belong to node instances and
live in the result store, so a Run record carries no outputs. Any number of Runs
may be active in one Project.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # The API owner restarted while the Run was unfinished. Stored results stay
    # valid; a rerun resumes from the fresh frontier.
    INTERRUPTED = "interrupted"


ACTIVE_RUN_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.RUNNING})
FINISHED_RUN_STATUSES: frozenset[RunStatus] = frozenset(RunStatus) - ACTIVE_RUN_STATUSES


class RunTransitionError(ValueError):
    """A finished Run was asked to finish again."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RunTarget:
    """One node instance a Run wants fresh, inside the Run's root Graph.

    ``call_path`` lists the call node ids entered to reach the instance,
    outermost first; it is empty for a node of the root Graph itself.
    """

    node_id: str
    call_path: tuple[str, ...] = ()


@dataclass
class Run:
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    """The root Graph the Run expands. Ids of Graphs inside a Project are strings."""
    targets: tuple[RunTarget, ...]
    """Empty means every node of the root Graph."""
    started_by_user_id: UUID | None
    id: UUID = field(default_factory=uuid4)
    status: RunStatus = RunStatus.RUNNING
    created_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("Run timestamps must be timezone-aware")
        if self.finished_at is not None and self.finished_at.tzinfo is None:
            raise ValueError("Run timestamps must be timezone-aware")

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_RUN_STATUSES

    def finish(
        self,
        status: RunStatus,
        *,
        error: str | None = None,
        at: datetime | None = None,
    ) -> None:
        if status in ACTIVE_RUN_STATUSES:
            raise RunTransitionError("A Run finishes in a finished status")
        if not self.is_active:
            raise RunTransitionError(
                f"Run {self.id} already finished as {self.status.value}"
            )
        stamp = at or _utc_now()
        if stamp.tzinfo is None:
            raise ValueError("Run timestamps must be timezone-aware")
        self.status = status
        self.finished_at = stamp
        self.error = error


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "FINISHED_RUN_STATUSES",
    "Run",
    "RunStatus",
    "RunTarget",
    "RunTransitionError",
]

"""Per-computation lifecycle as a pure transition table (ADR 0020)."""

from enum import StrEnum


class ComputationState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ComputationEvent(StrEnum):
    DEPENDENCIES_SATISFIED = "dependencies_satisfied"
    START = "start"
    SUCCEED = "succeed"
    FAIL = "fail"
    SKIP = "skip"
    CANCEL = "cancel"


class IllegalTransitionError(Exception):
    def __init__(self, state: ComputationState, event: ComputationEvent) -> None:
        super().__init__(f"Illegal computation transition: {state} on {event}")
        self.state = state
        self.event = event


TERMINAL_STATES: frozenset[ComputationState] = frozenset(
    {
        ComputationState.SUCCEEDED,
        ComputationState.FAILED,
        ComputationState.SKIPPED,
        ComputationState.CANCELLED,
    }
)


def transition(state: ComputationState, event: ComputationEvent) -> ComputationState:
    """Return the next state or raise ``IllegalTransitionError``.

    pending --dependencies_satisfied--> ready --start--> running
    pending --skip--> skipped           running --succeed--> succeeded
    pending|ready|running --cancel--> cancelled
    running --fail--> failed
    Every other (state, event) pair, including any event from a terminal
    state, is illegal.
    """
    raise NotImplementedError

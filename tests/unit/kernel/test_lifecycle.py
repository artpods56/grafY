from itertools import product

import pytest

from grafy_core.kernel.lifecycle import (
    TERMINAL_STATES,
    ComputationEvent,
    ComputationState,
    IllegalTransitionError,
    transition,
)

LEGAL: dict[tuple[ComputationState, ComputationEvent], ComputationState] = {
    (ComputationState.PENDING, ComputationEvent.DEPENDENCIES_SATISFIED): (
        ComputationState.READY
    ),
    (ComputationState.READY, ComputationEvent.START): ComputationState.RUNNING,
    (ComputationState.RUNNING, ComputationEvent.SUCCEED): ComputationState.SUCCEEDED,
    (ComputationState.RUNNING, ComputationEvent.FAIL): ComputationState.FAILED,
    (ComputationState.PENDING, ComputationEvent.SKIP): ComputationState.SKIPPED,
    (ComputationState.PENDING, ComputationEvent.CANCEL): ComputationState.CANCELLED,
    (ComputationState.READY, ComputationEvent.CANCEL): ComputationState.CANCELLED,
    (ComputationState.RUNNING, ComputationEvent.CANCEL): ComputationState.CANCELLED,
}

ALL_PAIRS: list[tuple[ComputationState, ComputationEvent]] = list(
    product(ComputationState, ComputationEvent)
)

ILLEGAL_PAIRS: list[tuple[ComputationState, ComputationEvent]] = [
    pair for pair in ALL_PAIRS if pair not in LEGAL
]

TERMINAL_ORDER: list[ComputationState] = sorted(
    TERMINAL_STATES, key=lambda state: str(state.value)
)


def test_the_table_covers_every_state_and_event_pair() -> None:
    assert len(ALL_PAIRS) == len(ComputationState) * len(ComputationEvent) == 42
    assert len(LEGAL) == 8
    assert len(ILLEGAL_PAIRS) == 34


@pytest.mark.parametrize(
    ("state", "event"),
    ALL_PAIRS,
    ids=[f"{state}-{event}" for state, event in ALL_PAIRS],
)
def test_transition_matches_the_table_exactly(
    state: ComputationState,
    event: ComputationEvent,
) -> None:
    expected = LEGAL.get((state, event))
    if expected is None:
        with pytest.raises(IllegalTransitionError) as excinfo:
            transition(state, event)
        assert excinfo.value.state is state
        assert excinfo.value.event is event
    else:
        assert transition(state, event) is expected


@pytest.mark.parametrize("state", TERMINAL_ORDER)
@pytest.mark.parametrize("event", list(ComputationEvent))
def test_no_event_is_legal_from_a_terminal_state(
    state: ComputationState,
    event: ComputationEvent,
) -> None:
    assert state in TERMINAL_STATES
    with pytest.raises(IllegalTransitionError) as excinfo:
        transition(state, event)
    assert excinfo.value.state is state
    assert excinfo.value.event is event


def test_transition_is_pure_and_repeatable() -> None:
    first = transition(
        ComputationState.PENDING, ComputationEvent.DEPENDENCIES_SATISFIED
    )
    assert first is ComputationState.READY
    assert (
        transition(ComputationState.PENDING, ComputationEvent.DEPENDENCIES_SATISFIED)
        is ComputationState.READY
    )
    with pytest.raises(IllegalTransitionError):
        transition(ComputationState.PENDING, ComputationEvent.START)

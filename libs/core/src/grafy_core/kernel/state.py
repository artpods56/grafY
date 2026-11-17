"""Derived instance state (ADR 0020). Never stored."""

from enum import StrEnum
from typing import Literal, Protocol, overload

from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import ResultStore


class InstanceState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"


class InFlightView(Protocol):
    def in_flight(self, fingerprint: str) -> Literal["queued", "running"] | None: ...


@overload
async def derive_instance_state(
    *,
    instance: InstanceKey,
    fingerprint: str,
    store: ResultStore,
    in_flight: InFlightView,
    execution_local: Literal[False] = False,
) -> InstanceState: ...


@overload
async def derive_instance_state(
    *,
    instance: InstanceKey,
    fingerprint: str,
    store: ResultStore,
    in_flight: InFlightView,
    execution_local: Literal[True],
) -> InstanceState | None: ...


async def derive_instance_state(
    *,
    instance: InstanceKey,
    fingerprint: str,
    store: ResultStore,
    in_flight: InFlightView,
    execution_local: bool = False,
) -> InstanceState | None:
    """fresh if the fingerprint has a result; else running/queued if a
    computation for it is in flight; else failed if the instance's last
    failure is at this fingerprint; else stale.

    ``execution_local`` is a service node. It has no stored result, so the
    machine's stale answer is omitted: the instance shows an in-flight or
    failed condition, or nothing. A missing secret stays on the secret-status
    surface, not on this state.
    """
    if await store.get_result(fingerprint) is not None:
        state = InstanceState.FRESH
    else:
        flight = in_flight.in_flight(fingerprint)
        if flight == "running":
            state = InstanceState.RUNNING
        elif flight == "queued":
            state = InstanceState.QUEUED
        else:
            pointer = await store.get_pointer(instance)
            if (
                pointer is not None
                and pointer.last_failure is not None
                and pointer.last_failure.fingerprint == fingerprint
            ):
                state = InstanceState.FAILED
            else:
                state = InstanceState.STALE
    if execution_local and state is InstanceState.STALE:
        return None
    return state

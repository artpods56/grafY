"""Derived instance state (ADR 0020). Never stored."""

from enum import StrEnum
from typing import Literal, Protocol

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


async def derive_instance_state(
    *,
    instance: InstanceKey,
    fingerprint: str,
    store: ResultStore,
    in_flight: InFlightView,
) -> InstanceState:
    """fresh if the fingerprint has a result; else running/queued if a
    computation for it is in flight; else failed if the instance's last
    failure is at this fingerprint; else stale."""
    raise NotImplementedError

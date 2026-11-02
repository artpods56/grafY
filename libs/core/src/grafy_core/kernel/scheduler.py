"""Ready-set scheduler: Runs are demand sets over single-flight computations."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import ExpandedInstance, InstanceKey
from grafy_core.kernel.lifecycle import ComputationState
from grafy_core.kernel.results import ResultStore

type RunId = str


@dataclass(frozen=True, slots=True)
class ComputationPlan:
    """One unit of work, keyed by fingerprint.

    ``instances`` are every instance whose current fingerprint is
    ``fingerprint`` (two calls with the same inputs share one computation);
    ``representative`` is the one handed to the runner. ``depends_on`` lists
    fingerprints of upstream computations that are in the same plan, i.e. that
    were stale; fresh upstreams are not listed.
    """

    fingerprint: str
    representative: ExpandedInstance
    instances: tuple[InstanceKey, ...]
    depends_on: frozenset[str]
    upstream_fingerprints: Mapping[InstanceKey, str]


@dataclass(frozen=True, slots=True)
class RunPlan:
    """The stale part of the upstream closure of a Run's targets."""

    targets: tuple[InstanceKey, ...]
    computations: Mapping[str, ComputationPlan]  # by fingerprint


@dataclass(frozen=True, slots=True)
class ComputationRequest:
    fingerprint: str
    instance: ExpandedInstance
    upstream_fingerprints: Mapping[InstanceKey, str]


type ComputationRunner = Callable[
    [ComputationRequest], Awaitable[Mapping[str, ArtifactOutputValue]]
]
"""Raises to fail. Cancellation arrives as ``asyncio.CancelledError``."""


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: RunId
    status: Literal["succeeded", "failed", "cancelled"]
    computations: Mapping[str, ComputationState]  # fingerprint -> final state
    failures: Mapping[str, str]  # fingerprint -> message


class Scheduler(Protocol):
    """One concurrency budget; single-flight per fingerprint across Runs."""

    async def submit(self, run_id: RunId, plan: RunPlan) -> None:
        """Register a Run's demand. A fingerprint already in flight gains this
        Run as a demander; one with a stored result is skipped; a terminal
        failed/skipped/cancelled one is replaced by a fresh attempt."""
        ...

    async def cancel(self, run_id: RunId) -> None:
        """Withdraw this Run's demand. A computation is cancelled only when no
        active Run still demands it."""
        ...

    async def wait(self, run_id: RunId) -> RunResult: ...

    def in_flight(self, fingerprint: str) -> Literal["queued", "running"] | None: ...


def build_scheduler(
    *,
    store: ResultStore,
    runner: ComputationRunner,
    concurrency: int,
) -> Scheduler:
    raise NotImplementedError


__all__: Sequence[str] = [
    "ComputationPlan",
    "ComputationRequest",
    "ComputationRunner",
    "RunId",
    "RunPlan",
    "RunResult",
    "Scheduler",
    "build_scheduler",
]

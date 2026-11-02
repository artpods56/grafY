"""Ready-set scheduler: Runs are demand sets over single-flight computations."""

import asyncio
import contextlib
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Protocol

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import ExpandedInstance, InstanceKey
from grafy_core.kernel.lifecycle import (
    TERMINAL_STATES,
    ComputationEvent,
    ComputationState,
    transition,
)
from grafy_core.kernel.results import FailureRecord, ResultStore

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


_FAILED_STATES: frozenset[ComputationState] = frozenset(
    {ComputationState.FAILED, ComputationState.SKIPPED}
)
"""Upstream outcomes that make a pending computation skipped rather than run."""

_UNHEALTHY_STATES: frozenset[ComputationState] = _FAILED_STATES | frozenset(
    {ComputationState.CANCELLED}
)
"""Outcomes that keep a Run from reporting success."""


@dataclass(eq=False)
class _Computation:
    """One attempt at one fingerprint, shared by every Run that joined it."""

    plan: ComputationPlan
    state: ComputationState = ComputationState.PENDING
    demanders: set[RunId] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    dependencies: list[_Computation] = field(default_factory=list)
    failure: str | None = None


@dataclass
class _Run:
    """A demand set: the computation objects this Run joined, in plan order."""

    run_id: RunId
    joined: list[_Computation] = field(default_factory=list)
    withdrawn: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)
    result: RunResult | None = None


def _run_result(run: _Run) -> RunResult:
    states = {record.plan.fingerprint: record.state for record in run.joined}
    failures = {
        record.plan.fingerprint: record.failure or ""
        for record in run.joined
        if record.state is ComputationState.FAILED
    }
    status: Literal["succeeded", "failed", "cancelled"]
    if run.withdrawn:
        status = "cancelled"
    elif any(state in _UNHEALTHY_STATES for state in states.values()):
        status = "failed"
    else:
        status = "succeeded"
    return RunResult(
        run_id=run.run_id,
        status=status,
        computations=MappingProxyType(states),
        failures=MappingProxyType(failures),
    )


class _Scheduler:
    """One ready set, one concurrency budget, one attempt per fingerprint.

    The only mutable scheduler state is a record per fingerprint and a record per
    Run. Every state change funnels through ``lifecycle.transition`` and is
    followed by a dispatch, which is a plain synchronous sweep: nothing here
    sleeps, polls or sets a timer, so a Run finishes exactly when the last
    computation it joined reaches a terminal state.
    """

    def __init__(
        self,
        *,
        store: ResultStore,
        runner: ComputationRunner,
        concurrency: int,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency must be at least 1, got {concurrency}")
        self._store = store
        self._runner = runner
        self._concurrency = concurrency
        # The one attempt per fingerprint that Runs may currently join. A fresh
        # attempt for a terminal fingerprint replaces the entry, so an old Run
        # keeps its own record and its own answer.
        self._records: dict[str, _Computation] = {}
        self._runs: dict[RunId, _Run] = {}
        self._ready: deque[_Computation] = deque()
        self._running: set[_Computation] = set()

    # Demand ---------------------------------------------------------------

    async def submit(self, run_id: RunId, plan: RunPlan) -> None:
        """Join every computation of ``plan``, creating the ones that are missing.

        Validation runs first and registers nothing, so a rejected plan leaves no
        half-known Run behind.
        """
        if run_id in self._runs:
            raise ValueError(f"Run {run_id!r} has already been submitted")

        computations = plan.computations
        for fingerprint, computation in computations.items():
            for dependency in sorted(computation.depends_on):
                if dependency in computations:
                    continue
                if await self._store.get_result(dependency) is not None:
                    continue
                raise ValueError(
                    f"Computation {fingerprint!r} depends on {dependency!r}, which "
                    "is neither a computation of this plan nor a stored result: a "
                    "plan must be closed under its dependencies"
                )

        run = _Run(run_id=run_id)
        self._runs[run_id] = run
        joined: dict[str, _Computation] = {}
        for fingerprint, computation in computations.items():
            joined[fingerprint] = await self._join(run_id, computation)
            run.joined.append(joined[fingerprint])
        for fingerprint, computation in computations.items():
            self._wire(joined[fingerprint], joined, computation.depends_on)

        self._dispatch()

    async def _join(
        self,
        run_id: RunId,
        computation: ComputationPlan,
    ) -> _Computation:
        fingerprint = computation.fingerprint
        if await self._store.get_result(fingerprint) is not None:
            # Reported as succeeded and never scheduled. This record is not in
            # ``_records``: it belongs to this Run alone and is already terminal.
            return _Computation(plan=computation, state=ComputationState.SUCCEEDED)

        record = self._records.get(fingerprint)
        if record is None or record.state in TERMINAL_STATES:
            # No attempt yet, or the last one failed, was skipped or was
            # cancelled: a rerun retries, so this is a fresh attempt.
            record = _Computation(plan=computation)
            self._records[fingerprint] = record
        record.demanders.add(run_id)
        return record

    def _wire(
        self,
        record: _Computation,
        joined: Mapping[str, _Computation],
        depends_on: frozenset[str],
    ) -> None:
        """Point the record at the objects this Run joined for its upstreams."""
        for dependency in sorted(depends_on):
            upstream = joined.get(dependency)
            # A dependency outside ``joined`` is satisfied by the result store and
            # needs no edge: it can never stop this computation from running.
            if upstream is None or upstream in record.dependencies:
                continue
            record.dependencies.append(upstream)

    # Cancellation ---------------------------------------------------------

    async def cancel(self, run_id: RunId) -> None:
        """Withdraw this Run's demand. Computations nobody else wants follow it."""
        run = self._runs.get(run_id)
        if run is None or run.result is not None:
            return
        run.withdrawn = True

        tasks: list[asyncio.Task[None]] = []
        for record in run.joined:
            record.demanders.discard(run_id)
            if record.state in TERMINAL_STATES or record.demanders:
                # Another Run still needs it: its outcome is that Run's business.
                continue
            self._apply(record, ComputationEvent.CANCEL)
            self._running.discard(record)
            if record.task is not None:
                record.task.cancel()
                tasks.append(record.task)
        for task in tasks:
            # The runner sees ``CancelledError`` before the withdrawal returns.
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # The withdrawn Run is answered now, with the states its computations
        # have at this moment. It does not wait for a computation that another
        # Run still demands.
        self._finish_run(run)
        self._dispatch()

    # Waiting and reading --------------------------------------------------

    async def wait(self, run_id: RunId) -> RunResult:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run {run_id!r}")
        await run.done.wait()
        if run.result is None:  # pragma: no cover - the event is set with it
            raise RuntimeError(f"Run {run_id!r} completed without a result")
        return run.result

    def in_flight(self, fingerprint: str) -> Literal["queued", "running"] | None:
        record = self._records.get(fingerprint)
        if record is None:
            return None
        if record.state in (ComputationState.PENDING, ComputationState.READY):
            return "queued"
        if record.state is ComputationState.RUNNING:
            return "running"
        return None

    # Dispatch -------------------------------------------------------------

    def _dispatch(self) -> None:
        self._resolve_pending()
        self._start_ready()
        self._complete_runs()

    def _resolve_pending(self) -> None:
        """Decide every pending computation, repeating until nothing changes.

        A failed or skipped upstream skips this computation and that verdict
        travels down the graph, so one sweep is not enough: the second round sees
        the skips the first one just made.
        """
        changed = True
        while changed:
            changed = False
            for record in list(self._records.values()):
                if record.state is not ComputationState.PENDING:
                    continue
                upstream = [dependency.state for dependency in record.dependencies]
                if any(state in _FAILED_STATES for state in upstream):
                    self._apply(record, ComputationEvent.SKIP)
                elif any(state is ComputationState.CANCELLED for state in upstream):
                    self._apply(record, ComputationEvent.CANCEL)
                elif all(state is ComputationState.SUCCEEDED for state in upstream):
                    self._apply(record, ComputationEvent.DEPENDENCIES_SATISFIED)
                    self._ready.append(record)
                else:
                    continue
                changed = True

    def _start_ready(self) -> None:
        while len(self._running) < self._concurrency and self._ready:
            record = self._ready.popleft()
            if record.state is not ComputationState.READY:
                # Cancelled while it waited its turn; the budget never moved.
                continue
            self._apply(record, ComputationEvent.START)
            self._running.add(record)
            record.task = asyncio.create_task(self._execute(record))

    async def _execute(self, record: _Computation) -> None:
        fingerprint = record.plan.fingerprint
        request = ComputationRequest(
            fingerprint=fingerprint,
            instance=record.plan.representative,
            upstream_fingerprints=record.plan.upstream_fingerprints,
        )
        try:
            outputs = await self._runner(request)
            # The result belongs to the fingerprint the computation started with,
            # even if the document moved on while the runner was out.
            await self._store.put_result(fingerprint, outputs)
            for instance in record.plan.instances:
                await self._store.record_success(instance, fingerprint)
        except asyncio.CancelledError:
            # ``cancel`` already moved this computation to cancelled; the record
            # is not ours to touch again, only to leave.
            raise
        except Exception as exc:
            # Failures live on the instance pointers, never in the result store.
            record.failure = str(exc) or exc.__class__.__name__
            with contextlib.suppress(Exception):
                await self._record_failure(record)
            self._finish(record, ComputationEvent.FAIL)
        else:
            self._finish(record, ComputationEvent.SUCCEED)

    async def _record_failure(self, record: _Computation) -> None:
        failure = FailureRecord(
            fingerprint=record.plan.fingerprint,
            message=record.failure or "",
            failed_at=datetime.now(UTC),
        )
        for instance in record.plan.instances:
            await self._store.record_failure(instance, failure)

    def _apply(self, record: _Computation, event: ComputationEvent) -> None:
        record.state = transition(record.state, event)

    def _finish(self, record: _Computation, event: ComputationEvent) -> None:
        if record.state in TERMINAL_STATES:
            # Cancelled in the middle of writing to the store: the withdrawal won.
            return
        self._apply(record, event)
        self._running.discard(record)
        self._dispatch()

    def _complete_runs(self) -> None:
        for run in list(self._runs.values()):
            if run.result is not None:
                continue
            if any(record.state not in TERMINAL_STATES for record in run.joined):
                continue
            self._finish_run(run)

    def _finish_run(self, run: _Run) -> None:
        run.result = _run_result(run)
        for record in run.joined:
            record.demanders.discard(run.run_id)
            if (
                not record.demanders
                and self._records.get(
                    record.plan.fingerprint,
                )
                is record
            ):
                # Nobody remembers this attempt any more. A later Run that needs
                # the fingerprint reads the store, or starts a fresh attempt.
                del self._records[record.plan.fingerprint]
        run.joined.clear()
        run.done.set()


def build_scheduler(
    *,
    store: ResultStore,
    runner: ComputationRunner,
    concurrency: int,
) -> Scheduler:
    return _Scheduler(store=store, runner=runner, concurrency=concurrency)


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

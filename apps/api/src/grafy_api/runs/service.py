"""The Run service: Runs as demand over the kernel scheduler (ADR 0020).

Everything the room and the HTTP routes need to know about running a Project goes
through here: start a Run, cancel one, read Runs, read instance state, read an
instance's last result, and hear about document edits. What it is *not* is a
second scheduler: the kernel's ``Scheduler`` owns computations, single-flight per
fingerprint and ref-counted by the Runs that demand them, so two Runs in one
Project share a computation and cancelling one only withdraws its own demand.

The three pieces of local state, and why each is allowed to exist:

* **One scheduler per Project**, built on first use. It is the Project's one
  concurrency budget, and it dies with this process — that is why a restart marks
  unfinished Runs interrupted instead of resuming them.
* **One run watcher task per active Run**, which waits for its Run, writes the
  outcome to the Run record, announces it, and asks for an instance publish. The
  watcher is the only writer of a Run's finish, so a concurrent cancel cannot
  race it for the row.
* **A dirty flag per Project**, which coalesces the many computation transitions of
  one burst into one instance-state publish. State is derived from the document
  and the store rather than carried in the notification, so one bit says all.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from grafy_api.runs.ports import (
    ComputationRunnerFactory,
    FingerprintFactsFactory,
    InstanceStateSnapshot,
    ProjectDocumentSource,
    RunEvents,
    RunNotFoundError,
    RunRejectedError,
)
from grafy_api.runs.state import InstanceStateTracker
from grafy_core.domain.runs import Run, RunStatus, RunTarget
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.instances import ExpandedGraph, InstanceKey
from grafy_core.kernel.lifecycle import ComputationState
from grafy_core.kernel.planning import plan_run
from grafy_core.kernel.project import (
    ProjectDocument,
    ProjectDocumentError,
    UnknownGraphError,
)
from grafy_core.kernel.results import InstancePointer, ResultStore, StoredResult
from grafy_core.kernel.scheduler import (
    RunResult,
    Scheduler,
    build_scheduler,
)
from grafy_core.kernel.state import (
    InFlightView,
    InstanceState,
    derive_instance_state,
)
from grafy_core.ports.runs import RunUnitOfWorkPort

#: What a Run says when this process stopped watching it mid-flight.
INTERRUPTED_ERROR = "the API owner restarted while this Run was running"


class _NoComputationInFlight:
    """The in-flight view of a Project this process is not scheduling."""

    def in_flight(self, fingerprint: str) -> None:
        del fingerprint
        return None


_NO_COMPUTATION = _NoComputationInFlight()


logger = logging.getLogger(__name__)

SHUTDOWN_STOP_TIMEOUT_SECONDS = 5.0
"""How long shutdown waits for a task it wants to stop before it insists.

Long enough for a publish or a Run's finish to land its transaction, short enough that a
task wedged in somebody else's call is reported in this process rather than becoming the
reason the container is killed.
"""


@dataclass
class _ProjectRuntime:
    """One Project's live scheduling and publish coalescing.

    The store is the Workspace-scoped one every read and every computation of
    this Project shares, so a fingerprint written by a computation is the same
    object a read looks the instance up in.
    """

    workspace_id: UUID
    project_id: UUID
    store: ResultStore
    tracker: InstanceStateTracker = field(default_factory=InstanceStateTracker)
    publish_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    scheduler: Scheduler | None = None
    dirty: bool = False
    publish_task: asyncio.Task[None] | None = None
    stopping: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class _WatchedRun:
    """An active Run, the Project it runs in, and the task waiting for it."""

    runtime: _ProjectRuntime
    task: asyncio.Task[None]


class _TransitionsAnnounced:
    """``SchedulerListener`` adapter: a moved computation means a publish is owed.

    The fingerprint and its new state are deliberately unread. Instance state is
    derived from the document, the store and what is in flight, so a transition
    only says "derive it again" and a burst of transitions owes one derivation.
    """

    def __init__(
        self,
        runtime: _ProjectRuntime,
        announce: Callable[[_ProjectRuntime], None],
    ) -> None:
        self._runtime = runtime
        self._announce = announce

    def computation_changed(
        self,
        fingerprint: str,
        state: ComputationState,
    ) -> None:
        del fingerprint, state
        self._announce(self._runtime)


class RunService:
    """Runs, instance state and instance results for the Projects of one API owner."""

    def __init__(
        self,
        *,
        documents: ProjectDocumentSource,
        uow_factory: Callable[[], RunUnitOfWorkPort],
        result_store_factory: Callable[[UUID], ResultStore],
        facts: FingerprintFactsFactory,
        runners: ComputationRunnerFactory,
        events: RunEvents,
        concurrency: int,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency must be at least 1, got {concurrency}")
        self._documents = documents
        self._uow_factory = uow_factory
        self._result_store_factory = result_store_factory
        self._facts = facts
        self._runners = runners
        self._events = events
        self._concurrency = concurrency
        self._runtimes: dict[tuple[UUID, UUID], _ProjectRuntime] = {}
        self._watchers: dict[UUID, _WatchedRun] = {}
        self._closing = False

    # Runs ------------------------------------------------------------------

    async def start(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        targets: Sequence[RunTarget],
        started_by_user_id: UUID | None,
    ) -> Run:
        """Record a demand for ``targets`` to become fresh, and start satisfying it.

        The Run is planned against the document as it is at this moment: a later
        edit does not change what this Run asked for, and its computations store
        what they produce under the fingerprints they started with.
        """
        document = await self._documents.head_document(workspace_id, project_id)
        expanded = self._expand(document, graph_id=graph_id, project_id=project_id)
        facts = await self._facts.for_project(
            workspace_id=workspace_id,
            project_id=project_id,
            document=document,
        )
        fingerprints = compute_fingerprints(expanded, facts)
        keys = _resolve_targets(expanded, targets)
        runtime = self._runtime(workspace_id, project_id)
        plan = await plan_run(
            graph=expanded,
            fingerprints=fingerprints,
            targets=keys,
            store=runtime.store,
        )
        run = Run(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id=graph_id,
            targets=tuple(targets),
            started_by_user_id=started_by_user_id,
        )
        await self._record(run)
        if not plan.computations:
            # Nothing was stale: the Run asked for what already held. It is still
            # a Run, still recorded, and still announced.
            await self._events.run_started(run)
            await self._finish(run, runtime, RunStatus.SUCCEEDED, None)
            return run

        await self._scheduler_for(runtime).submit(str(run.id), plan)
        await self._events.run_started(run)
        self._watchers[run.id] = _WatchedRun(
            runtime=runtime,
            task=asyncio.create_task(self._watch(run.id, runtime, run)),
        )
        return run

    async def cancel(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
    ) -> Run:
        """Withdraw one Run's demand. Finished Runs are returned untouched.

        Computations another active Run still demands keep running, and this call
        waits for the Run's watcher so the returned record carries the finish the
        watcher wrote rather than a status this call guessed.
        """
        run = await self.get_run(
            workspace_id=workspace_id,
            project_id=project_id,
            run_id=run_id,
        )
        if not run.is_active:
            return run
        runtime = self._runtimes.get((workspace_id, project_id))
        watched = self._watchers.get(run_id)
        if runtime is not None and runtime.scheduler is not None:
            await runtime.scheduler.cancel(str(run_id))
        if watched is not None:
            await watched.task
            return await self.get_run(
                workspace_id=workspace_id,
                project_id=project_id,
                run_id=run_id,
            )
        # No watcher means nothing was in flight for it in this process: the row
        # is the whole of it, and it is this call's to finish.
        run.finish(RunStatus.CANCELLED)
        await self._save(run)
        await self._events.run_finished(run)
        if runtime is not None:
            await self._publish_now(runtime)
        return run

    async def get_run(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
    ) -> Run:
        async with self._uow_factory() as uow:
            run = await uow.runs.get(workspace_id, project_id, run_id)
        if run is None:
            raise RunNotFoundError(
                f"Project {project_id} of workspace {workspace_id} has no run {run_id}"
            )
        return run

    async def list_runs(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Run]:
        async with self._uow_factory() as uow:
            return await uow.runs.list_for_project(
                workspace_id,
                project_id,
                active_only=active_only,
                limit=limit,
            )

    async def recover_after_restart(self) -> list[Run]:
        """Mark every unfinished Run interrupted, and leave the results alone.

        In-flight computations died with the process that held them. Stored
        results did not, so the next Run resumes from the fresh frontier instead
        of recomputing what this one already produced.
        """
        async with self._uow_factory() as uow:
            runs = await uow.runs.interrupt_unfinished(
                at=datetime.now(UTC),
                error=INTERRUPTED_ERROR,
            )
            await uow.commit()
        return runs

    async def close(self) -> None:
        """Stop every task this service started and forget every Project.

        Runs left running stay running in the store: nobody watched their computations, and
        the next startup marks them interrupted, which is the honest record of what
        happened.

        Nothing here cancels a task that may be holding a database connection. A task
        cancelled inside `greenlet_spawn` abandons that connection: the pool's terminate
        fails with the same `CancelledError`, the aiosqlite worker sits at `tx.get()` for
        ever, and the next checkout from that pool is a request that never returns. What a
        shutdown that reached did was park its test thread in `thread.join()` with the app
        loop idle, forty-five minutes of CI and no failure line.

        So the order is: announce that the service is closing, end the Runs so their
        watchers have something to finish writing, then wait for the tasks. Only a task that
        outlives the deadline is cancelled, and it is named in the log.
        """

        self._closing = True
        runtimes = list(self._runtimes.values())
        for runtime in runtimes:
            runtime.stopping.set()
        watched = list(self._watchers.items())
        self._watchers.clear()
        tasks = [entry.task for _, entry in watched]
        tasks += [
            runtime.publish_task
            for runtime in runtimes
            if runtime.publish_task is not None
        ]
        stragglers = await self._settle(tasks, reason="run_service_close")
        # Withdrawing each Run's demand stops the computations it was the last to need, and
        # comes last on purpose: a watcher that wrote a finish for a Run this service merely
        # stopped watching would be writing a fact nobody observed. The rows stay running,
        # which is what a restart expects to find and mark interrupted.
        # A publish started by the withdrawals above is still this service's to reap.
        late = [
            runtime.publish_task
            for runtime in self._runtimes.values()
            if runtime.publish_task is not None and not runtime.publish_task.done()
        ]
        for run_id, entry in watched:
            if entry.runtime.scheduler is not None:
                await entry.runtime.scheduler.cancel(str(run_id))
        stragglers += await self._settle(late, reason="run_service_close_late_publish")
        self._runtimes.clear()
        if stragglers:
            logger.error(
                "run_service_close_incomplete tasks=%s deadline_seconds=%s",
                len(stragglers),
                SHUTDOWN_STOP_TIMEOUT_SECONDS,
            )

    async def _settle(
        self, tasks: Sequence[asyncio.Task[None]], *, reason: str
    ) -> list[asyncio.Task[None]]:
        """Wait for tasks to stop on their own, then insist, within a deadline.

        Waiting is the point: a publish or a Run's finish is a transaction, and tearing a
        task out of one leaves a connection the pool never gets back. A task still running
        when the deadline passes is cancelled and reported, because a task nobody holds is
        the other way to hang a process.
        """

        live = [task for task in tasks if not task.done()]
        if not live:
            return []
        done, pending = await asyncio.wait(live, timeout=SHUTDOWN_STOP_TIMEOUT_SECONDS)
        await asyncio.gather(*done, return_exceptions=True)
        if not pending:
            return []
        logger.warning(
            "run_service_stop_timeout reason=%s tasks=%s deadline_seconds=%s",
            reason,
            len(pending),
            SHUTDOWN_STOP_TIMEOUT_SECONDS,
        )
        for task in pending:
            task.cancel()
        done, remaining = await asyncio.wait(
            pending, timeout=SHUTDOWN_STOP_TIMEOUT_SECONDS
        )
        await asyncio.gather(*done, return_exceptions=True)
        return list(remaining)

    # Instance state --------------------------------------------------------

    async def instance_states(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str | None = None,
    ) -> list[InstanceStateSnapshot]:
        snapshots = await self._snapshots(
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if graph_id is None:
            return snapshots
        return [snapshot for snapshot in snapshots if snapshot.key.graph_id == graph_id]

    async def instance_result(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        key: InstanceKey,
    ) -> tuple[InstanceStateSnapshot, StoredResult | None]:
        """An instance's current state and the last result it produced.

        The result is read through the instance's pointer, not through the
        current fingerprint, which is what lets a stale instance keep showing what
        it last produced.
        """
        snapshots = await self._snapshots(
            workspace_id=workspace_id,
            project_id=project_id,
        )
        snapshot = next(
            (item for item in snapshots if item.key == key),
            None,
        )
        if snapshot is None:
            raise RunRejectedError(
                "unknown_target",
                f"{_describe_key(key)} is not an instance of project {project_id}",
            )
        pointer = await self._result_store_factory(workspace_id).get_pointer(key)
        if pointer is None or pointer.last_result_fingerprint is None:
            return snapshot, None
        result = await self._result_store_factory(
            workspace_id,
        ).get_result(pointer.last_result_fingerprint)
        return snapshot, result

    async def project_changed(
        self, *, workspace_id: UUID, project_id: UUID, wait: bool = True
    ) -> None:
        """Re-derive every instance of a Project after its document moved.

        An edit changes fingerprints, not computations: what is in flight keeps
        running and stores its result under the fingerprint it started with, while
        the instances it fed read as stale until that result lands and a Run asks
        for the new fingerprints.
        """
        runtime = self._runtime(workspace_id, project_id)
        if wait:
            await self._publish_now(runtime)
        else:
            # A room may disappear as soon as command acceptance is delivered. Its
            # cancellation must not interrupt SQL statements in the state derivation.
            self._transition_moved(runtime)

    # Internals -------------------------------------------------------------

    def _expand(
        self,
        document: ProjectDocument,
        *,
        graph_id: str,
        project_id: UUID,
    ) -> ExpandedGraph:
        try:
            return expand_graph(document, graph_id, project_id=str(project_id))
        except UnknownGraphError as exc:
            raise RunRejectedError("unknown_graph", str(exc)) from exc
        except ProjectDocumentError as exc:
            raise RunRejectedError("invalid_document", str(exc)) from exc

    def _runtime(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> _ProjectRuntime:
        """This Project's live state, built on first use and kept for the process."""
        key = (workspace_id, project_id)
        runtime = self._runtimes.get(key)
        if runtime is None:
            runtime = _ProjectRuntime(
                workspace_id=workspace_id,
                project_id=project_id,
                store=self._result_store_factory(workspace_id),
            )
            self._runtimes[key] = runtime
        return runtime

    def _scheduler_for(self, runtime: _ProjectRuntime) -> Scheduler:
        """The Project's one concurrency budget, with its publish listener."""
        if runtime.scheduler is None:
            runtime.scheduler = build_scheduler(
                store=runtime.store,
                runner=self._runners.for_project(
                    workspace_id=runtime.workspace_id,
                    project_id=runtime.project_id,
                    store=runtime.store,
                ),
                concurrency=self._concurrency,
                listener=_TransitionsAnnounced(runtime, self._transition_moved),
            )
        return runtime.scheduler

    async def _watch(self, run_id: UUID, runtime: _ProjectRuntime, run: Run) -> None:
        """Wait this Run out, then be the one that writes its finish.

        `close()` asks this task to stop by setting `runtime.stopping`, rather than
        cancelling it. The difference is the database: a task cancelled inside
        `greenlet_spawn` cannot hand its connection back, and a shutdown that reaches does
        that to whichever task it cancelled, so stopping happens at a point that holds
        nothing. Stopping early also writes nothing: a Run left running is what the next
        startup expects to find, and marks interrupted.
        """

        waiting = asyncio.ensure_future(self._scheduler_for(runtime).wait(str(run_id)))
        stopping = asyncio.ensure_future(runtime.stopping.wait())
        try:
            done, _ = await asyncio.wait(
                {waiting, stopping}, return_when=asyncio.FIRST_COMPLETED
            )
            if waiting in done:
                result = waiting.result()
                await self._finish(
                    run, runtime, RunStatus(result.status), _run_error(result)
                )
        finally:
            for task in (waiting, stopping):
                if not task.done():
                    task.cancel()
            await asyncio.gather(waiting, stopping, return_exceptions=True)
            self._watchers.pop(run_id, None)

    async def _finish(
        self,
        run: Run,
        runtime: _ProjectRuntime,
        status: RunStatus,
        error: str | None,
    ) -> None:
        run.finish(status, error=error)
        await self._save(run)
        await self._events.run_finished(run)
        await self._publish_now(runtime)

    async def _record(self, run: Run) -> None:
        async with self._uow_factory() as uow:
            await uow.runs.add(run)
            await uow.commit()

    async def _save(self, run: Run) -> None:
        async with self._uow_factory() as uow:
            await uow.runs.save(run)
            await uow.commit()

    def _transition_moved(self, runtime: _ProjectRuntime) -> None:
        """Mark a Project dirty from a computation transition, outside the loop.

        Called by the scheduler listener with no await point of its own: it sets a
        flag and makes sure something will drain it, which is all a synchronous
        announcement can ask for.

        Once the service is closing it asks for nothing. A transition announced during
        shutdown would spawn a publish task no one holds any more — `close()` has already
        collected them — and that task would do its SQL over a database the lifespan is on
        its way to disposing, on a loop somebody is waiting to close.
        """
        if self._closing:
            return
        runtime.dirty = True
        if runtime.publish_task is None or runtime.publish_task.done():
            runtime.publish_task = asyncio.create_task(self._drain_publishes(runtime))
            runtime.publish_task.add_done_callback(self._publish_done)

    @staticmethod
    def _publish_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "project_instance_publish_failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _publish_now(self, runtime: _ProjectRuntime) -> None:
        runtime.dirty = True
        await self._drain_publishes(runtime)

    async def _drain_publishes(self, runtime: _ProjectRuntime) -> None:
        """Publish until nothing has moved since the last publish.

        The lock is what keeps two passes from publishing out of order; the flag is
        what makes a burst of transitions one publish instead of one apiece.
        """
        async with runtime.publish_lock:
            while runtime.dirty and not runtime.stopping.is_set():
                runtime.dirty = False
                await self._publish(runtime)

    async def _publish(self, runtime: _ProjectRuntime) -> None:
        changed, removed = runtime.tracker.diff(
            await self._snapshots(
                workspace_id=runtime.workspace_id,
                project_id=runtime.project_id,
            )
        )
        if not changed and not removed:
            return
        await self._events.instances_changed(
            workspace_id=runtime.workspace_id,
            project_id=runtime.project_id,
            changed=changed,
            removed=removed,
        )

    async def _snapshots(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[InstanceStateSnapshot]:
        """Every instance of every Graph of the head document, with its state.

        Each Graph is expanded on its own because a Run targets one Graph and its
        callees: the same node of a callee reached from two callers is two
        instances, and an instance nobody can reach is not on anyone's canvas.
        """
        document = await self._documents.head_document(workspace_id, project_id)
        facts = await self._facts.for_project(
            workspace_id=workspace_id,
            project_id=project_id,
            document=document,
        )
        store = self._result_store_factory(workspace_id)
        runtime = self._runtimes.get((workspace_id, project_id))
        in_flight: InFlightView = (
            _NO_COMPUTATION
            if runtime is None or runtime.scheduler is None
            else runtime.scheduler
        )
        snapshots: list[InstanceStateSnapshot] = []
        for graph in document.graphs:
            expanded = self._expand(document, graph_id=graph.id, project_id=project_id)
            fingerprints = compute_fingerprints(expanded, facts)
            for key in expanded.order:
                fingerprint = fingerprints[key]
                state = await derive_instance_state(
                    instance=key,
                    fingerprint=fingerprint,
                    store=store,
                    in_flight=in_flight,
                )
                pointer = await store.get_pointer(key)
                snapshots.append(
                    InstanceStateSnapshot(
                        key=key,
                        state=state,
                        fingerprint=fingerprint,
                        last_result_fingerprint=(
                            None if pointer is None else pointer.last_result_fingerprint
                        ),
                        error=_pointer_error(state, pointer),
                    )
                )
        return snapshots


def _pointer_error(
    state: InstanceState,
    pointer: InstancePointer | None,
) -> str | None:
    """The message an instance carries while failed; nothing else has one."""
    if (
        state is not InstanceState.FAILED
        or pointer is None
        or pointer.last_failure is None
    ):
        return None
    return pointer.last_failure.message


def _run_error(result: RunResult) -> str | None:
    """Why a Run did not succeed, in the computations' own words."""
    if result.status != "failed":
        return None
    messages = [result.failures[key] for key in sorted(result.failures)]
    if messages:
        return "; ".join(messages)
    # A Run can also fail by having a computation skipped or cancelled with nobody
    # to blame, in which case there is no message to carry and the fingerprints
    # that did not succeed are the only account of it.
    stalled = sorted(
        fingerprint
        for fingerprint, state in result.computations.items()
        if state is not ComputationState.SUCCEEDED
    )
    return "computations did not succeed: " + ", ".join(stalled)


def _describe_key(key: InstanceKey) -> str:
    call_path = "/".join(key.call_path) if key.call_path else "(root)"
    return f"instance node={key.node_id!r} graph={key.graph_id!r} call_path={call_path}"


def _resolve_targets(
    expanded: ExpandedGraph,
    targets: Sequence[RunTarget],
) -> list[InstanceKey]:
    """Turn a Run's target list into keys of this expansion.

    No targets means every instance of the root Graph itself: a callee's instances
    are reached through the call nodes that place them, so the root's own set is
    the whole Graph and never the union of everything inlined into it. A target
    that names no instance is a request nobody can satisfy, and the Run that made
    it is rejected rather than quietly narrowed to what does exist.
    """
    if not targets:
        return [key for key in expanded.order if not key.call_path]
    keys: list[InstanceKey] = []
    for target in targets:
        matches = [
            key
            for key in expanded.order
            if key.node_id == target.node_id and key.call_path == target.call_path
        ]
        if len(matches) != 1:
            raise RunRejectedError(
                "unknown_target",
                f"target node={target.node_id!r} "
                f"call_path={'/'.join(target.call_path) or '(root)'} is not an "
                f"instance of graph {expanded.graph_id!r}",
            )
        keys.append(matches[0])
    return keys


__all__ = ["INTERRUPTED_ERROR", "RunService"]

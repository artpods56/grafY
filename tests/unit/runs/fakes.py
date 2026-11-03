"""In-memory fakes for the Run service, its facts and its seams.

Nothing here reaches a database, a room or a sandbox. The service is tested
against the kernel's real ``InMemoryResultStore`` and a real ``PluginRegistry``
and ``RegistryImplementationDigests`` built over a throwaway family written to
``tmp_path``, so the two catalog questions a Run answers — what does this node
run, and may its result be reused — are answered by real code. What is faked is
the four seams the service is built on: the head document source, the run unit of
work, the computation runner, and the event fan-out.

The fake runner moves only on ``asyncio.Event`` objects and the fake events land
in an ``asyncio.Queue``: a test states which moment of a computation it observes,
and nothing races a clock.
"""

import asyncio
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from copy import copy
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from uuid import UUID

import pytest

from grafy_api.runs.facts import ApplicationFactsFactory
from grafy_api.runs.ports import InstanceStateSnapshot
from grafy_api.runs.service import RunService
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import Node
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphOrigin,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.runs import Run, RunStatus, RunTarget
from grafy_core.kernel.implementation_identity import RegistryImplementationDigests
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.results import ResultStore
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    GraphDefinition,
    ProjectDocument,
)
from grafy_core.kernel.results import (
    FailureRecord,
    InstancePointer,
    StoredResult,
)
from grafy_core.kernel.scheduler import ComputationRequest, ComputationRunner
from grafy_core.kernel.state import InstanceState
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeSecretInput,
    Plugin,
    PluginRegistry,
)
from tests.unit.kernel.builders import make_edge, make_node, make_origin

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000a01")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000a02")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000b01")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000b02")
USER_ID = UUID("00000000-0000-0000-0000-000000000c01")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000d01")

VALUE_OPERATOR = "test.value"
NEVER_OPERATOR = "test.never"
CALLEE_OUTPUT_PORT = "r"  # the output port ``child_graph`` publishes
SECRET_OPERATOR = "test.secret"
GHOST_OPERATOR = "test.ghost"

#: Turns a scheduler or an event queue that stops moving into a failed test.
HANG_GUARD_SECONDS = 10


# --- Documents ---------------------------------------------------------------


def value_node(node_id: str, *, value: int = 1) -> GraphNode:
    return make_node(node_id, operator_id=VALUE_OPERATOR, config={"value": value})


def never_node(node_id: str) -> GraphNode:
    return make_node(node_id, operator_id=NEVER_OPERATOR)


def secret_node(node_id: str, *, credential: str = "prod") -> GraphNode:
    return make_node(
        node_id,
        operator_id=SECRET_OPERATOR,
        config={"credential": credential},
    )


def ghost_node(node_id: str) -> GraphNode:
    """A node the catalog does not register: no digest, no cache policy."""
    return make_node(node_id, operator_id=GHOST_OPERATOR)


def input_node(node_id: str, public_name: str) -> GraphNode:
    return make_node(
        node_id,
        operator_id=GRAPH_INPUT_OPERATOR_ID,
        config={"public_name": public_name},
    )


def output_node(node_id: str, public_name: str) -> GraphNode:
    return make_node(
        node_id,
        operator_id=GRAPH_OUTPUT_OPERATOR_ID,
        config={"public_name": public_name},
    )


def call_node(node_id: str, callee: str) -> GraphNode:
    return make_node(node_id, kind=CALL_NODE_KIND, operator_id=callee)


def edge(
    from_node: str,
    to_node: str,
    *,
    from_port: str = "value",
    to_port: str = "value",
    edge_id: str | None = None,
) -> GraphEdge:
    return make_edge(
        f"{from_node}->{to_node}" if edge_id is None else edge_id,
        from_node,
        to_node,
        from_port=from_port,
        to_port=to_port,
    )


def origin(
    to_node: str,
    *,
    to_port: str = "value",
    origin_id: str | None = None,
    mark: str = "one",
) -> GraphOrigin:
    return make_origin(
        f"o-{to_node}" if origin_id is None else origin_id,
        to_node,
        to_port=to_port,
        value=artifact(mark),
    )


def artifact(mark: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=ARTIFACT_ID,
        artifact_type="scalar.integer",
        schema_version=1,
        content_hash=hashlib.sha256(mark.encode("utf-8")).hexdigest(),
    )


def graph(
    graph_id: str,
    nodes: Sequence[GraphNode],
    edges: Sequence[GraphEdge] = (),
    origins: Sequence[GraphOrigin] = (),
    *,
    refresh: Mapping[str, int] | None = None,
) -> GraphDefinition:
    return GraphDefinition(
        id=graph_id,
        name=f"Graph {graph_id}",
        document=GraphDocument(
            nodes=tuple(nodes),
            edges=tuple(edges),
            origins=tuple(origins),
        ),
        refresh_generations=dict(refresh or {}),
    )


def document(*graphs: GraphDefinition) -> ProjectDocument:
    return ProjectDocument(graphs=graphs)


def main_graph(*, value: int = 1, with_sink: bool = True) -> GraphDefinition:
    """``main``: ``value`` -> ``sink``. ``value`` is the node every test edits."""
    nodes: list[GraphNode] = [value_node("value", value=value)]
    edges: list[GraphEdge] = []
    if with_sink:
        nodes.append(never_node("sink"))
        edges.append(edge("value", "sink"))
    return graph("main", nodes, edges)


def side_graph(node_id: str = "solo", *, value: int = 7) -> GraphDefinition:
    """A second root Graph, reachable by name only: nothing calls it.

    Its own value on purpose: a node computing the same thing as one in ``main``
    would share that computation rather than be a second piece of work.
    """
    return graph("side", [value_node(node_id, value=value)])


def child_graph(
    *,
    credential: str = "prod",
    refresh: Mapping[str, int] | None = None,
) -> GraphDefinition:
    """``child``: input ``x`` -> secret-carrying ``f`` -> output ``r``."""
    return graph(
        "child",
        [
            input_node("in", "x"),
            secret_node("f", credential=credential),
            output_node("out", "r"),
        ],
        [edge("in", "f"), edge("f", "out")],
        refresh=refresh,
    )


def caller_graph(*call_node_ids: str, mark: str | None = None) -> GraphDefinition:
    """``main`` calling ``child`` once per named call node, then publishing it.

    Each call site feeds its callee a value of its own unless ``mark`` names one
    value for them all, which is when the two calls become one computation.
    """
    nodes: list[GraphNode] = [call_node(node_id, "child") for node_id in call_node_ids]
    nodes.extend(never_node(f"seen-by-{node_id}") for node_id in call_node_ids)
    # The callee's own output port is what the caller reads, which is how expansion
    # knows to rewire the edge onto the instance the call placed.
    edges = [
        edge(node_id, f"seen-by-{node_id}", from_port=CALLEE_OUTPUT_PORT)
        for node_id in call_node_ids
    ]
    origins = [
        origin(node_id, to_port="x", mark=mark or f"fed-by-{node_id}")
        for node_id in call_node_ids
    ]
    return graph("main", nodes, edges, origins)


def _syspath(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    # pytest's own syspath_prepend is unannotated; setattr is typed.
    monkeypatch.setattr(sys, "path", [path, *sys.path])


# --- The catalog -------------------------------------------------------------


class ValueConfig(NodeConfig):
    value: int = 0


class CredentialConfig(NodeConfig):
    credential: str = "default"


class NoInput(NodeInput):
    pass


class NoOutput(NodeOutput):
    pass


#: No test executes a node: the Run service plans and announces, a runner runs.
_NOT_EXECUTABLE = "the Run service never executes an operator itself"


class ValueNode(Node[ValueConfig, NoInput, NoOutput]):
    async def run(self, context: object, config: object, inputs: object, /) -> NoOutput:
        raise AssertionError(_NOT_EXECUTABLE)


class NeverNode(Node[ValueConfig, NoInput, NoOutput]):
    async def run(self, context: object, config: object, inputs: object, /) -> NoOutput:
        raise AssertionError(_NOT_EXECUTABLE)


class SecretNode(Node[CredentialConfig, NoInput, NoOutput]):
    async def run(self, context: object, config: object, inputs: object, /) -> NoOutput:
        raise AssertionError(_NOT_EXECUTABLE)


@dataclass(frozen=True, slots=True)
class FakeCatalog:
    """What the deployment knows at startup: a catalog and its implementation digests."""

    registry: PluginRegistry
    digests: RegistryImplementationDigests


def build_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    registers: Sequence[str] = (VALUE_OPERATOR, NEVER_OPERATOR, SECRET_OPERATOR),
) -> FakeCatalog:
    """A real registry and real digests over a throwaway family in ``tmp_path``.

    Every registered operator points at the same family module, so two operators
    differ in implementation identity only by id and version — which is what a
    fingerprint test needs to see move. ``registers`` is what the deployment of the
    test claims to know: leave one out to see what a document naming it meets.
    """
    family = tmp_path / "fake_runs_family"
    family.mkdir(parents=True, exist_ok=True)
    (family / "__init__.py").write_text("", encoding="utf-8")
    (family / "nodes.py").write_text("NODE = 1\n", encoding="utf-8")
    # pytest's own syspath_prepend is unannotated; setattr is typed.
    _syspath(monkeypatch, str(tmp_path))
    lock = tmp_path / "uv.lock"
    lock.write_text(
        "version = 1\n\n"
        '[[package]]\nname = "fake-runs-family"\nversion = "0.1.0"\n'
        'source = { virtual = "." }\n',
        encoding="utf-8",
    )

    plugin = Plugin(slug="fake.runs", title="Fake runs")
    api_key = NodeSecretInput(
        name="api_key",
        title="API key",
        config_dependencies=("credential",),
    )
    if VALUE_OPERATOR in registers:
        plugin.node(
            operator_id=VALUE_OPERATOR,
            version=1,
            title="Value",
            cache_policy=NodeCachePolicy.EXACT,
        )(ValueNode)
    if NEVER_OPERATOR in registers:
        plugin.node(
            operator_id=NEVER_OPERATOR,
            version=1,
            title="Never",
            cache_policy=NodeCachePolicy.NEVER,
        )(NeverNode)
    if SECRET_OPERATOR in registers:
        plugin.node(
            operator_id=SECRET_OPERATOR,
            version=1,
            title="Secret",
            cache_policy=NodeCachePolicy.EXACT,
            secret_inputs=(api_key,),
            required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
        )(SecretNode)

    registry = PluginRegistry()
    registry.install(plugin)
    module = "fake_runs_family.nodes"
    return FakeCatalog(
        registry=registry,
        digests=RegistryImplementationDigests(
            {
                (operator_id, 1): module
                for operator_id in (VALUE_OPERATOR, NEVER_OPERATOR, SECRET_OPERATOR)
            },
            uv_lock=lock,
        ),
    )


class FakeSecretRevisionResolver:
    """``SecretRevisionResolver`` standing where the secret store would.

    Every call is recorded with the identity it was asked under, so a test can see
    that one node's secret is read once however many call paths reach it, and can
    make one secret unset to see what the facts do then.
    """

    def __init__(self, revisions: Mapping[str, str] | None = None) -> None:
        self.revisions: dict[str, str] = dict(revisions or {})
        self.unset: set[str] = set()
        self.calls: list[tuple[str, str, str, str, tuple[tuple[str, str], ...]]] = []

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id
        self.calls.append(
            (
                str(project_id),
                graph_id,
                node_id,
                name,
                tuple(sorted((key, str(value)) for key, value in dependencies.items())),
            )
        )
        if name in self.unset:
            raise NodeSecretUnavailableError(f"secret {name!r} has never been set")
        return self.revisions.get(name, f"revision-of-{name}")


def facts_factory(
    catalog: FakeCatalog,
    secrets: FakeSecretRevisionResolver | None = None,
) -> ApplicationFactsFactory:
    return ApplicationFactsFactory(
        registry=catalog.registry,
        digests=catalog.digests,
        secrets=secrets if secrets is not None else FakeSecretRevisionResolver(),
    )


# --- The head document -------------------------------------------------------


class MissingProjectError(LookupError):
    """What the document source says about a Project it does not hold."""


class FakeProjectDocumentSource:
    """The live head documents, with the edits a collaborator would make."""

    def __init__(
        self,
        project: ProjectDocument | None = None,
        *,
        other_project: ProjectDocument | None = None,
    ) -> None:
        self.documents: dict[UUID, ProjectDocument] = {}
        if project is not None:
            self.documents[PROJECT_ID] = project
        if other_project is not None:
            self.documents[OTHER_PROJECT_ID] = other_project
        self.reads = 0

    @property
    def document(self) -> ProjectDocument:
        """The head of the Project every test here starts from."""
        return self.documents[PROJECT_ID]

    def edit(self, document: ProjectDocument) -> None:
        """Move the head, the way a committed command batch would."""
        self.documents[PROJECT_ID] = document

    async def head_document(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectDocument:
        del workspace_id
        self.reads += 1
        try:
            return self.documents[project_id]
        except KeyError:
            raise MissingProjectError(f"no project {project_id}") from None


# --- Run rows ----------------------------------------------------------------


class FakeRunRepository:
    """Run rows in a list. Every read returns a detached copy, as a table would."""

    def __init__(self) -> None:
        self.rows: list[Run] = []
        self.added: list[UUID] = []
        self.saved: list[UUID] = []

    def insert(self, run: Run) -> None:
        """Seed a row directly, the way a previous process left it behind."""
        self.rows.append(copy(run))

    async def add(self, run: Run) -> None:
        if any(row.id == run.id for row in self.rows):
            raise AssertionError(f"run {run.id} added twice")
        self.rows.append(copy(run))
        self.added.append(run.id)

    async def get(
        self,
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
    ) -> Run | None:
        for row in reversed(self.rows):
            if (
                row.id == run_id
                and row.workspace_id == workspace_id
                and row.project_id == project_id
            ):
                return copy(row)
        return None

    async def save(self, run: Run) -> None:
        for index, row in enumerate(self.rows):
            if row.id == run.id:
                self.rows[index] = copy(run)
                self.saved.append(run.id)
                return
        raise AssertionError(f"run {run.id} is not a stored row")

    async def list_for_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Run]:
        rows = [
            row
            for row in self.rows
            if row.workspace_id == workspace_id and row.project_id == project_id
        ]
        if active_only:
            rows = [row for row in rows if row.is_active]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        return [copy(row) for row in rows[:limit]]

    async def interrupt_unfinished(self, *, at: datetime, error: str) -> list[Run]:
        unfinished = [row for row in self.rows if row.is_active]
        for row in unfinished:
            row.finish(RunStatus.INTERRUPTED, error=error, at=at)
        return [copy(row) for row in unfinished]


class FakeResultStoreRepository:
    """The results half of the unit of work.

    The service reads and writes results through the Workspace-scoped
    ``ResultStore``, never through a transaction, so this repository exists to
    make the unit of work a real one rather than a half-implemented stand-in.
    """

    def __init__(self) -> None:
        self.results: dict[tuple[UUID, str], StoredResult] = {}
        self.pointers: dict[tuple[UUID, InstanceKey], InstancePointer] = {}

    async def artifact_is_referenced(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> bool:
        for (workspace, _), result in self.results.items():
            if workspace != workspace_id:
                continue
            for value in result.outputs.values():
                refs = (
                    value.item_refs
                    if isinstance(value, ArtifactRefSequence)
                    else (value,)
                )
                if any(ref.artifact_id == artifact_id for ref in refs):
                    return True
        return False

    async def get_result(
        self,
        workspace_id: UUID,
        fingerprint: str,
    ) -> StoredResult | None:
        return self.results.get((workspace_id, fingerprint))

    async def put_result_if_absent(
        self,
        workspace_id: UUID,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
        *,
        created_at: datetime,
    ) -> StoredResult:
        key = (workspace_id, fingerprint)
        existing = self.results.get(key)
        if existing is not None:
            return existing
        stored = StoredResult(
            fingerprint=fingerprint,
            outputs=dict(outputs),
            created_at=created_at,
        )
        self.results[key] = stored
        return stored

    async def get_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
    ) -> InstancePointer | None:
        return self.pointers.get((workspace_id, instance))

    async def list_pointers(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> Mapping[InstanceKey, InstancePointer]:
        del project_id
        return {
            instance: pointer
            for (workspace, instance), pointer in self.pointers.items()
            if workspace == workspace_id
        }

    async def set_success_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        fingerprint: str,
    ) -> None:
        self.pointers[(workspace_id, instance)] = InstancePointer(
            last_result_fingerprint=fingerprint,
            last_failure=None,
        )

    async def set_failure_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        existing = self.pointers.get((workspace_id, instance))
        self.pointers[(workspace_id, instance)] = InstancePointer(
            last_result_fingerprint=(
                None if existing is None else existing.last_result_fingerprint
            ),
            last_failure=failure,
        )


class FakeRunUnitOfWork:
    """A run unit of work whose commit is a counter: the rows are already written."""

    def __init__(
        self,
        runs: FakeRunRepository,
        results: FakeResultStoreRepository,
    ) -> None:
        self._runs = runs
        self._results = results
        self.commits = 0
        self.rollbacks = 0

    @property
    def runs(self) -> FakeRunRepository:
        return self._runs

    @property
    def results(self) -> FakeResultStoreRepository:
        return self._results

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeUnitOfWorkFactory:
    """Unit of works over one pair of in-memory repositories."""

    def __init__(self) -> None:
        self.runs = FakeRunRepository()
        self.results = FakeResultStoreRepository()
        self.opened = 0
        self._current: FakeRunUnitOfWork | None = None

    def __call__(self) -> FakeRunUnitOfWork:
        self.opened += 1
        self._current = FakeRunUnitOfWork(self.runs, self.results)
        return self._current


# --- Computations ------------------------------------------------------------


class FakeRunner:
    """``ComputationRunner`` that moves only when a test releases it.

    Gated by node id, which is the name a test has: one gate covers exactly the
    one computation the scheduler runs for that node, however many Runs demand it
    and however many instances share its fingerprint.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.requests: list[ComputationRequest] = []
        self.cancelled: list[str] = []
        self.released: list[str] = []
        self.failures: dict[str, str] = {}
        self._started: dict[str, asyncio.Event] = {}
        self._release: dict[str, asyncio.Event] = {}

    def reset(self) -> None:
        """Treat the next computations as a new batch.

        What the runner was asked for is kept, so a later Run's fingerprint can still
        be set against an earlier one's; what has begun, and the gates holding it, are
        forgotten.
        """
        self.calls = []
        self.cancelled = []
        self.released = []
        self._started = {}
        self._release = {}

    def started(self, node_id: str) -> asyncio.Event:
        return self._started.setdefault(node_id, asyncio.Event())

    def release(self, node_id: str) -> asyncio.Event:
        return self._release.setdefault(node_id, asyncio.Event())

    def fail_with(self, node_id: str, message: str) -> None:
        self.failures[node_id] = message

    async def run(
        self,
        request: ComputationRequest,
    ) -> Mapping[str, ArtifactOutputValue]:
        node_id = request.instance.key.node_id
        self.calls.append(node_id)
        self.requests.append(request)
        self.started(node_id).set()
        try:
            await self.release(node_id).wait()
        except asyncio.CancelledError:
            self.cancelled.append(node_id)
            raise
        self.released.append(node_id)
        failure = self.failures.get(node_id)
        if failure is not None:
            raise RuntimeError(failure)
        # The output is addressed by the fingerprint it was computed for, so a
        # test can tell which attempt a stored result came from.
        return {"result": artifact(f"output-of-{request.fingerprint}")}


class FakeComputationRunnerFactory:
    """Hands out the one fake runner, recording which Projects asked for one."""

    def __init__(self, runner: FakeRunner) -> None:
        self.runner = runner
        self.built: list[tuple[UUID, UUID]] = []

    def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: ResultStore,
    ) -> ComputationRunner:
        del store
        self.built.append((workspace_id, project_id))
        return self.runner.run


# --- Events ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    kind: str
    run: Run | None = None
    changed: tuple[InstanceStateSnapshot, ...] = ()
    removed: tuple[InstanceKey, ...] = ()

    def state_of(self, node_id: str) -> InstanceState:
        for snapshot in self.changed:
            if snapshot.key.node_id == node_id:
                return snapshot.state
        raise AssertionError(
            f"node {node_id!r} is not in this publish: "
            + ", ".join(
                f"{snapshot.key.node_id}={snapshot.state}" for snapshot in self.changed
            )
        )

    def has_published(self, node_id: str) -> bool:
        return any(snapshot.key.node_id == node_id for snapshot in self.changed)


class FakeRunEvents:
    """Every announcement the service made, in the order it made them.

    Waiting is by mark, not by consumption: a test says "the announcement made after
    this point, about this Run" and cannot swallow an event another wait wanted, in
    whichever order they happen to be resumed.
    """

    def __init__(self) -> None:
        self.recorded: list[RecordedEvent] = []
        self._waiters: list[asyncio.Future[None]] = []

    def mark(self) -> int:
        """A position in the recording; a later wait looks only past it."""
        return len(self.recorded)

    async def run_started(self, run: Run) -> None:
        self._publish(RecordedEvent(kind="run_started", run=run))

    async def run_finished(self, run: Run) -> None:
        self._publish(RecordedEvent(kind="run_finished", run=run))

    async def instances_changed(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        changed: Sequence[InstanceStateSnapshot],
        removed: Sequence[InstanceKey],
    ) -> None:
        del workspace_id, project_id
        self._publish(
            RecordedEvent(
                kind="instances_changed",
                changed=tuple(changed),
                removed=tuple(removed),
            )
        )

    def _publish(self, event: RecordedEvent) -> None:
        self.recorded.append(event)
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    def _matching(
        self, kind: str, after: int, run_id: UUID | None
    ) -> list[RecordedEvent]:
        found = [event for event in self.recorded[after:] if event.kind == kind]
        if run_id is None:
            return found
        return [
            event for event in found if event.run is not None and event.run.id == run_id
        ]

    async def until(
        self,
        kind: str,
        *,
        after: int = 0,
        run_id: UUID | None = None,
    ) -> RecordedEvent:
        """The first event of ``kind`` recorded after ``after``, for ``run_id``."""
        while True:
            found = self._matching(kind, after, run_id)
            if found:
                return found[0]
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            async with asyncio.timeout(HANG_GUARD_SECONDS):
                await waiter

    def published(self) -> list[RecordedEvent]:
        return [event for event in self.recorded if event.kind == "instances_changed"]

    def kinds(self) -> list[str]:
        return [event.kind for event in self.recorded]


# --- Harness -----------------------------------------------------------------


class FakeResultStoreFactory:
    """One store per Workspace: a fingerprint never crosses a Workspace boundary."""

    def __init__(self) -> None:
        self.stores: dict[UUID, InMemoryResultStore] = {}
        self.asks: list[UUID] = []

    def __call__(self, workspace_id: UUID) -> InMemoryResultStore:
        self.asks.append(workspace_id)
        store = self.stores.get(workspace_id)
        if store is None:
            store = InMemoryResultStore()
            self.stores[workspace_id] = store
        return store

    @property
    def store(self) -> InMemoryResultStore:
        return self.stores[WORKSPACE_ID]


@dataclass
class RunServiceHarness:
    """Everything a Run service test needs, wired to one another.

    ``restart`` builds the next API owner over the same rows, documents and
    result store, which is the only way to watch a process boundary from inside a
    single test.
    """

    documents: FakeProjectDocumentSource
    unit_of_work: FakeUnitOfWorkFactory
    store_factory: FakeResultStoreFactory
    builder: FakeComputationRunnerFactory
    runner: FakeRunner
    events: FakeRunEvents
    secrets: FakeSecretRevisionResolver
    catalog: FakeCatalog
    service: RunService
    concurrency: int

    @property
    def store(self) -> InMemoryResultStore:
        return self.store_factory.store

    @property
    def rows(self) -> FakeRunRepository:
        return self.unit_of_work.runs

    async def start(
        self,
        *,
        graph_id: str = "main",
        targets: Sequence[RunTarget] = (),
        project_id: UUID = PROJECT_ID,
        workspace_id: UUID = WORKSPACE_ID,
    ) -> Run:
        return await self.service.start(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id=graph_id,
            targets=targets,
            started_by_user_id=USER_ID,
        )

    async def started(self, run_id: UUID | None = None, *, after: int = 0) -> Run:
        """The Run this service announced as started (by default, the next one)."""
        event = await self.events.until("run_started", after=after, run_id=run_id)
        assert event.run is not None
        return event.run

    async def finished(self, run_id: UUID | None = None, *, after: int = 0) -> Run:
        """The Run this service announced as finished (by default, the next one)."""
        event = await self.events.until("run_finished", after=after, run_id=run_id)
        assert event.run is not None
        return event.run

    async def published(self, *, after: int = 0) -> RecordedEvent:
        """The next instance-state delta published after ``after``."""
        return await self.events.until("instances_changed", after=after)

    def mark(self) -> int:
        return self.events.mark()

    async def running(self, *node_ids: str) -> None:
        """Hold until the scheduler has started each named computation."""
        for node_id in node_ids:
            async with asyncio.timeout(HANG_GUARD_SECONDS):
                await self.runner.started(node_id).wait()

    def release(self, *node_ids: str) -> None:
        """Let each named computation run to its end."""
        for node_id in node_ids:
            self.runner.release(node_id).set()

    def reset_runner(self) -> None:
        """Treat the next computations as a new batch, keeping what was requested."""
        self.runner.reset()

    async def complete(self, *node_ids: str, run_id: UUID | None = None) -> Run:
        """Release the named computations and take the Run they belonged to."""
        self.release(*node_ids)
        return await self.finished(run_id)

    async def states(self, graph_id: str | None = None) -> list[InstanceStateSnapshot]:
        return await self.service.instance_states(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            graph_id=graph_id,
        )

    def state_of(
        self,
        states: Sequence[InstanceStateSnapshot],
        node_id: str,
    ) -> InstanceState:
        for snapshot in states:
            if snapshot.key.node_id == node_id:
                return snapshot.state
        raise AssertionError(
            f"no state for node {node_id!r}: "
            + ", ".join(
                f"{snapshot.key.node_id}={snapshot.state}" for snapshot in states
            )
        )

    def restart(self) -> "RunServiceHarness":
        """A new API owner over the same rows, documents and stored results."""
        events = FakeRunEvents()
        runner = FakeRunner()
        service = RunService(
            documents=self.documents,
            uow_factory=self.unit_of_work,
            result_store_factory=self.store_factory,
            facts=facts_factory(self.catalog, self.secrets),
            runners=FakeComputationRunnerFactory(runner),
            events=events,
            concurrency=self.concurrency,
        )
        return RunServiceHarness(
            documents=self.documents,
            unit_of_work=self.unit_of_work,
            store_factory=self.store_factory,
            builder=FakeComputationRunnerFactory(runner),
            runner=runner,
            events=events,
            secrets=self.secrets,
            catalog=self.catalog,
            service=service,
            concurrency=self.concurrency,
        )

    async def close(self) -> None:
        await self.service.close()


def harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project: ProjectDocument | None = None,
    other_project: ProjectDocument | None = None,
    secrets: FakeSecretRevisionResolver | None = None,
    concurrency: int = 4,
    registers: Sequence[str] = (VALUE_OPERATOR, NEVER_OPERATOR, SECRET_OPERATOR),
) -> RunServiceHarness:
    """A Run service over fakes, with a real catalog and a real in-memory store."""
    catalog = build_catalog(tmp_path, monkeypatch, registers=registers)
    documents = FakeProjectDocumentSource(project, other_project=other_project)
    unit_of_work = FakeUnitOfWorkFactory()
    store_factory = FakeResultStoreFactory()
    runner = FakeRunner()
    builder = FakeComputationRunnerFactory(runner)
    events = FakeRunEvents()
    resolver = secrets if secrets is not None else FakeSecretRevisionResolver()
    service = RunService(
        documents=documents,
        uow_factory=unit_of_work,
        result_store_factory=store_factory,
        facts=facts_factory(catalog, resolver),
        runners=builder,
        events=events,
        concurrency=concurrency,
    )
    return RunServiceHarness(
        documents=documents,
        unit_of_work=unit_of_work,
        store_factory=store_factory,
        builder=builder,
        runner=runner,
        events=events,
        secrets=resolver,
        catalog=catalog,
        service=service,
        concurrency=concurrency,
    )


def run_row(
    *,
    status: RunStatus = RunStatus.RUNNING,
    workspace_id: UUID = WORKSPACE_ID,
    project_id: UUID = PROJECT_ID,
    graph_id: str = "main",
) -> Run:
    """A Run row for seeding the table directly."""
    return Run(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id=graph_id,
        targets=(),
        started_by_user_id=USER_ID,
        status=status,
        created_at=datetime.now(UTC),
    )


def node_ids(snapshots: Iterable[InstanceStateSnapshot]) -> set[str]:
    return {snapshot.key.node_id for snapshot in snapshots}


__all__ = [
    "ARTIFACT_ID",
    "GHOST_OPERATOR",
    "HANG_GUARD_SECONDS",
    "NEVER_OPERATOR",
    "OTHER_PROJECT_ID",
    "OTHER_WORKSPACE_ID",
    "PROJECT_ID",
    "SECRET_OPERATOR",
    "USER_ID",
    "VALUE_OPERATOR",
    "WORKSPACE_ID",
    "FakeCatalog",
    "FakeComputationRunnerFactory",
    "FakeProjectDocumentSource",
    "FakeResultStoreFactory",
    "FakeRunEvents",
    "FakeRunUnitOfWork",
    "FakeRunner",
    "FakeSecretRevisionResolver",
    "FakeUnitOfWorkFactory",
    "MissingProjectError",
    "RecordedEvent",
    "RunServiceHarness",
    "artifact",
    "build_catalog",
    "call_node",
    "caller_graph",
    "child_graph",
    "document",
    "edge",
    "facts_factory",
    "graph",
    "harness",
    "side_graph",
    "input_node",
    "main_graph",
    "never_node",
    "node_ids",
    "output_node",
    "run_row",
    "secret_node",
    "value_node",
]

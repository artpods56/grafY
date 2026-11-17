"""A service node is never planned; its fingerprint still reaches the consumer."""

from datetime import UTC, datetime
from typing import Literal

from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.planning import plan_run
from grafy_core.kernel.results import FailureRecord
from grafy_core.kernel.state import InstanceState, derive_instance_state
from tests.unit.kernel.builders import (
    ExpandedGraphBuilder,
    FakeFacts,
    make_node,
)


class FakeInFlight:
    def __init__(
        self,
        phases: dict[str, Literal["queued", "running"]] | None = None,
    ) -> None:
        self._phases: dict[str, Literal["queued", "running"]] = dict(phases or {})

    def in_flight(self, fingerprint: str) -> Literal["queued", "running"] | None:
        return self._phases.get(fingerprint)

SERVICE_OPERATOR = ("test.provider", 1)
CONSUMER_OPERATOR = ("test.consumer", 1)


def _service_graph(*, provider_label: str = "a"):
    builder = ExpandedGraphBuilder()
    provider = builder.add_instance(
        make_node(
            "provider",
            operator_id=SERVICE_OPERATOR[0],
            operator_version=SERVICE_OPERATOR[1],
            config={"label": provider_label},
        )
    )
    consumer = builder.add_instance(
        make_node(
            "consumer",
            operator_id=CONSUMER_OPERATOR[0],
            operator_version=CONSUMER_OPERATOR[1],
            config={},
        )
    )
    builder.connect(
        provider,
        consumer,
        from_port="reader",
        to_port="reader",
    )
    return builder.build(), {"provider": provider, "consumer": consumer}


async def test_a_service_node_is_never_in_the_run_plan() -> None:
    graph, keys = _service_graph()
    fingerprints = compute_fingerprints(graph, FakeFacts())
    store = InMemoryResultStore()

    plan = await plan_run(
        graph=graph,
        fingerprints=fingerprints,
        targets=[keys["consumer"]],
        store=store,
        service_operators={SERVICE_OPERATOR},
    )

    assert list(plan.computations) == [fingerprints[keys["consumer"]]]
    computation = plan.computations[fingerprints[keys["consumer"]]]
    assert computation.depends_on == frozenset()
    assert keys["provider"] in computation.upstream_fingerprints
    assert computation.service_sources[keys["provider"]].key == keys["provider"]


async def test_changing_the_provider_config_changes_the_consumer_fingerprint() -> None:
    first, keys = _service_graph(provider_label="a")
    second, _ = _service_graph(provider_label="b")
    first_prints = compute_fingerprints(first, FakeFacts())
    second_prints = compute_fingerprints(second, FakeFacts())

    assert first_prints[keys["provider"]] != second_prints[keys["provider"]]
    assert first_prints[keys["consumer"]] != second_prints[keys["consumer"]]


async def test_a_fresh_consumer_is_not_planned_so_its_provider_is_not_run() -> None:
    graph, keys = _service_graph()
    fingerprints = compute_fingerprints(graph, FakeFacts())
    store = InMemoryResultStore()
    await store.put_result(fingerprints[keys["consumer"]], {})

    plan = await plan_run(
        graph=graph,
        fingerprints=fingerprints,
        targets=[keys["consumer"]],
        store=store,
        service_operators={SERVICE_OPERATOR},
    )

    assert plan.computations == {}


async def test_a_service_node_is_not_stale_when_nothing_is_known() -> None:
    store = InMemoryResultStore()
    state = await derive_instance_state(
        instance=_service_graph()[1]["provider"],
        fingerprint="fp-provider",
        store=store,
        in_flight=FakeInFlight(),
        execution_local=True,
    )
    assert state is None


async def test_a_service_node_can_still_show_failed() -> None:
    graph, keys = _service_graph()
    store = InMemoryResultStore()
    fingerprint = "fp-provider"
    await store.record_failure(
        keys["provider"],
        FailureRecord(
            fingerprint=fingerprint,
            message="boom",
            failed_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        ),
    )

    state = await derive_instance_state(
        instance=keys["provider"],
        fingerprint=fingerprint,
        store=store,
        in_flight=FakeInFlight(),
        execution_local=True,
    )
    assert state is InstanceState.FAILED

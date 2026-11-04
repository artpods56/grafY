from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.results import FailureRecord
from grafy_core.kernel.state import InstanceState, derive_instance_state

FIRST_FINGERPRINT = "a" * 64
SECOND_FINGERPRINT = "b" * 64


class FakeInFlight:
    """InFlightView stand-in: a fingerprint -> phase table, no scheduler."""

    def __init__(
        self,
        phases: dict[str, Literal["queued", "running"]] | None = None,
    ) -> None:
        self._phases: dict[str, Literal["queued", "running"]] = dict(phases or {})

    def in_flight(self, fingerprint: str) -> Literal["queued", "running"] | None:
        return self._phases.get(fingerprint)


def _key(node_id: str = "node-1") -> InstanceKey:
    return InstanceKey(
        project_id="project-1",
        graph_id="graph-1",
        call_path=(),
        node_id=node_id,
    )


def _outputs(mark: str) -> dict[str, ArtifactOutputValue]:
    return {
        "value": ArtifactRef(
            artifact_id=UUID("00000000-0000-0000-0000-000000000101"),
            artifact_type="scalar.integer",
            schema_version=1,
            content_hash=mark * 64,
        )
    }


def _failure(fingerprint: str) -> FailureRecord:
    return FailureRecord(
        fingerprint=fingerprint,
        message="boom",
        failed_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
    )


async def test_a_stored_result_at_the_fingerprint_is_fresh() -> None:
    store = InMemoryResultStore()
    await store.put_result(FIRST_FINGERPRINT, _outputs("1"))

    state = await derive_instance_state(
        instance=_key(),
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.FRESH
    assert state == "fresh"


async def test_nothing_known_about_the_fingerprint_is_stale() -> None:
    store = InMemoryResultStore()

    state = await derive_instance_state(
        instance=_key(),
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.STALE


async def test_a_queued_computation_for_the_fingerprint_is_queued() -> None:
    store = InMemoryResultStore()

    state = await derive_instance_state(
        instance=_key(),
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight({FIRST_FINGERPRINT: "queued"}),
    )

    assert state is InstanceState.QUEUED


async def test_a_running_computation_for_the_fingerprint_is_running() -> None:
    store = InMemoryResultStore()

    state = await derive_instance_state(
        instance=_key(),
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight({FIRST_FINGERPRINT: "running"}),
    )

    assert state is InstanceState.RUNNING


async def test_a_failure_at_the_fingerprint_is_failed() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.record_failure(instance, _failure(FIRST_FINGERPRINT))

    state = await derive_instance_state(
        instance=instance,
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.FAILED


async def test_a_result_beats_a_failure_at_the_same_fingerprint() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.put_result(FIRST_FINGERPRINT, _outputs("1"))
    await store.record_failure(instance, _failure(FIRST_FINGERPRINT))

    state = await derive_instance_state(
        instance=instance,
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.FRESH


async def test_in_flight_beats_a_failure_at_the_same_fingerprint() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.record_failure(instance, _failure(FIRST_FINGERPRINT))

    running = await derive_instance_state(
        instance=instance,
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight({FIRST_FINGERPRINT: "running"}),
    )
    queued = await derive_instance_state(
        instance=instance,
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight({FIRST_FINGERPRINT: "queued"}),
    )

    assert running is InstanceState.RUNNING
    assert queued is InstanceState.QUEUED


async def test_a_failure_at_an_old_fingerprint_does_not_fail_a_new_one() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.record_failure(instance, _failure(FIRST_FINGERPRINT))

    state = await derive_instance_state(
        instance=instance,
        fingerprint=SECOND_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.STALE


async def test_a_stale_instance_keeps_pointing_at_its_last_result() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.put_result(FIRST_FINGERPRINT, _outputs("1"))
    await store.record_success(instance, FIRST_FINGERPRINT)

    state = await derive_instance_state(
        instance=instance,
        fingerprint=SECOND_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.STALE
    pointer = await store.get_pointer(instance)
    assert pointer is not None
    assert pointer.last_result_fingerprint == FIRST_FINGERPRINT


async def test_another_instances_failure_does_not_apply() -> None:
    store = InMemoryResultStore()
    await store.record_failure(_key("node-1"), _failure(FIRST_FINGERPRINT))

    state = await derive_instance_state(
        instance=_key("node-2"),
        fingerprint=FIRST_FINGERPRINT,
        store=store,
        in_flight=FakeInFlight(),
    )

    assert state is InstanceState.STALE

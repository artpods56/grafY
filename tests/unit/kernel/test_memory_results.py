from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID

import pytest

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.results import FailureRecord

PROJECT_ID = "project-1"
GRAPH_ID = "graph-1"
FIRST_FINGERPRINT = "a" * 64
SECOND_FINGERPRINT = "b" * 64


def _ref(mark: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=UUID("00000000-0000-0000-0000-000000000101"),
        artifact_type="scalar.integer",
        schema_version=1,
        content_hash=mark * 64,
    )


def _outputs(mark: str) -> dict[str, ArtifactOutputValue]:
    return {"value": _ref(mark)}


def _content_hash(
    outputs: Mapping[str, ArtifactOutputValue],
    port: str = "value",
) -> str | None:
    value = outputs[port]
    assert isinstance(value, ArtifactRef)
    return value.content_hash


def _key(node_id: str = "node-1") -> InstanceKey:
    return InstanceKey(
        project_id=PROJECT_ID,
        graph_id=GRAPH_ID,
        call_path=(),
        node_id=node_id,
    )


def _failure(fingerprint: str, message: str = "boom") -> FailureRecord:
    return FailureRecord(
        fingerprint=fingerprint,
        message=message,
        failed_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
    )


async def test_put_result_appends_a_result_with_a_created_at() -> None:
    store = InMemoryResultStore()

    stored = await store.put_result(FIRST_FINGERPRINT, _outputs("1"))

    assert stored.fingerprint == FIRST_FINGERPRINT
    assert stored.created_at.tzinfo is not None
    assert _content_hash(stored.outputs) == "1" * 64
    assert await store.get_result(FIRST_FINGERPRINT) is stored


async def test_get_result_is_none_for_an_unknown_fingerprint() -> None:
    store = InMemoryResultStore()

    assert await store.get_result(FIRST_FINGERPRINT) is None


async def test_put_result_is_first_write_wins() -> None:
    store = InMemoryResultStore()
    first = await store.put_result(FIRST_FINGERPRINT, _outputs("1"))

    second = await store.put_result(FIRST_FINGERPRINT, _outputs("2"))
    held = await store.get_result(FIRST_FINGERPRINT)

    assert second is first
    assert _content_hash(second.outputs) == "1" * 64
    assert held is not None
    assert held is first
    assert _content_hash(held.outputs) == "1" * 64


async def test_stored_outputs_are_a_read_only_defensive_copy() -> None:
    store = InMemoryResultStore()
    source = _outputs("1")
    original_ref = source["value"]
    assert isinstance(original_ref, ArtifactRef)

    stored = await store.put_result(FIRST_FINGERPRINT, source)

    # The store holds copies, so later caller edits cannot reach it.
    source["extra"] = _ref("9")
    original_ref.content_hash = "0" * 64
    assert set(stored.outputs) == {"value"}
    assert _content_hash(stored.outputs) == "1" * 64

    # The stored mapping itself rejects mutation, whatever its static type says.
    assert isinstance(stored.outputs, MappingProxyType)
    as_mapping = cast("MutableMapping[str, ArtifactOutputValue]", stored.outputs)
    with pytest.raises(TypeError):
        as_mapping["value"] = _ref("2")
    with pytest.raises(TypeError):
        del as_mapping["value"]
    assert _content_hash(stored.outputs) == "1" * 64


async def test_record_success_points_at_the_result_and_clears_the_failure() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.put_result(SECOND_FINGERPRINT, _outputs("2"))
    await store.record_failure(instance, _failure(FIRST_FINGERPRINT))

    await store.record_success(instance, SECOND_FINGERPRINT)

    pointer = await store.get_pointer(instance)
    assert pointer is not None
    assert pointer.last_result_fingerprint == SECOND_FINGERPRINT
    assert pointer.last_failure is None


async def test_record_failure_keeps_the_result_pointer() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.put_result(FIRST_FINGERPRINT, _outputs("1"))
    await store.record_success(instance, FIRST_FINGERPRINT)

    failure = _failure(SECOND_FINGERPRINT, message="upstream exploded")
    await store.record_failure(instance, failure)

    pointer = await store.get_pointer(instance)
    assert pointer is not None
    assert pointer.last_result_fingerprint == FIRST_FINGERPRINT
    assert pointer.last_failure is failure
    # The result itself is untouched: a stale node still shows what it produced.
    result = await store.get_result(FIRST_FINGERPRINT)
    assert result is not None
    assert _content_hash(result.outputs) == "1" * 64


async def test_record_failure_replaces_the_previous_failure() -> None:
    store = InMemoryResultStore()
    instance = _key()
    await store.record_failure(instance, _failure(FIRST_FINGERPRINT, message="first"))

    await store.record_failure(instance, _failure(FIRST_FINGERPRINT, message="second"))

    pointer = await store.get_pointer(instance)
    assert pointer is not None
    assert pointer.last_failure is not None
    assert pointer.last_failure.message == "second"
    assert pointer.last_result_fingerprint is None


async def test_record_success_for_an_unstored_fingerprint_raises_key_error() -> None:
    store = InMemoryResultStore()
    instance = _key()

    with pytest.raises(KeyError):
        await store.record_success(instance, FIRST_FINGERPRINT)

    assert await store.get_pointer(instance) is None


async def test_get_pointer_is_none_for_an_unknown_instance() -> None:
    store = InMemoryResultStore()
    await store.record_failure(_key("node-1"), _failure(FIRST_FINGERPRINT))

    assert await store.get_pointer(_key("node-2")) is None


async def test_pointers_are_kept_per_instance() -> None:
    store = InMemoryResultStore()
    await store.put_result(FIRST_FINGERPRINT, _outputs("1"))
    first, second = _key("node-1"), _key("node-2")

    await store.record_success(first, FIRST_FINGERPRINT)
    await store.record_failure(second, _failure(SECOND_FINGERPRINT))

    first_pointer = await store.get_pointer(first)
    second_pointer = await store.get_pointer(second)
    assert first_pointer is not None
    assert first_pointer.last_result_fingerprint == FIRST_FINGERPRINT
    assert first_pointer.last_failure is None
    assert second_pointer is not None
    assert second_pointer.last_result_fingerprint is None
    assert second_pointer.last_failure is not None

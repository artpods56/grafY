"""The instance-state tracker: what moved since the last thing was published.

State itself is derived, so the only memory here is the snapshot that was last
sent out. These tests move one thing at a time — a state, a fingerprint, a key
that vanishes — and demand that exactly that thing, and nothing else, comes back
from the next diff. No clocks, no sleeps, no I/O: the tracker is a dictionary and
the tests hold it to being a correct one.
"""

from collections.abc import Sequence

from grafy_api.runs.ports import InstanceStateSnapshot
from grafy_api.runs.state import InstanceStateTracker
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.state import InstanceState
from tests.unit.kernel.builders import make_key


def snapshot(
    node_id: str,
    state: InstanceState = InstanceState.FRESH,
    fingerprint: str = "fp-1",
    last_result: str | None = "fp-1",
    error: str | None = None,
) -> InstanceStateSnapshot:
    return InstanceStateSnapshot(
        key=make_key(node_id),
        state=state,
        fingerprint=fingerprint,
        last_result_fingerprint=last_result,
        error=error,
    )


def nodes(snapshots: Sequence[InstanceStateSnapshot]) -> list[str]:
    return [snapshot.key.node_id for snapshot in snapshots]


def keys(removed: Sequence[InstanceKey]) -> list[str]:
    return [key.node_id for key in removed]


def test_the_first_diff_reports_everything_as_changed() -> None:
    tracker = InstanceStateTracker()
    snapshots = [snapshot("a"), snapshot("b")]

    changed, removed = tracker.diff(snapshots)

    assert changed == snapshots
    assert removed == []


def test_republishing_the_same_state_changes_nothing() -> None:
    tracker = InstanceStateTracker()
    snapshots = [snapshot("a"), snapshot("b")]
    tracker.diff(snapshots)

    changed, removed = tracker.diff(snapshots)

    assert changed == []
    assert removed == []


def test_only_the_instance_that_moved_comes_back() -> None:
    tracker = InstanceStateTracker()
    tracker.diff([snapshot("a"), snapshot("b")])

    changed, removed = tracker.diff(
        [snapshot("a"), snapshot("b", state=InstanceState.STALE, last_result="fp-0")]
    )

    assert nodes(changed) == ["b"]
    assert removed == []


def test_a_moved_fingerprint_alone_is_a_change_even_at_the_same_state() -> None:
    tracker = InstanceStateTracker()
    tracker.diff([snapshot("a", fingerprint="fp-1")])

    changed, removed = tracker.diff([snapshot("a", fingerprint="fp-2")])

    assert nodes(changed) == ["a"]
    assert changed[0].fingerprint == "fp-2"
    assert removed == []


def test_changes_come_back_in_the_order_they_were_given() -> None:
    tracker = InstanceStateTracker()
    tracker.diff([snapshot("first"), snapshot("second")])

    changed, _ = tracker.diff(
        [
            snapshot("second", state=InstanceState.QUEUED),
            snapshot("first", state=InstanceState.RUNNING),
        ]
    )

    assert nodes(changed) == ["second", "first"]


def test_an_instance_the_document_dropped_is_removed_once() -> None:
    tracker = InstanceStateTracker()
    tracker.diff([snapshot("a"), snapshot("b")])

    changed, removed = tracker.diff([snapshot("a")])
    again_changed, again_removed = tracker.diff([snapshot("a")])

    assert nodes(changed) == []
    assert keys(removed) == ["b"]
    assert again_changed == []
    assert again_removed == []


def test_an_instance_the_document_added_is_changed_not_removed() -> None:
    tracker = InstanceStateTracker()
    tracker.diff([snapshot("a")])

    changed, removed = tracker.diff([snapshot("a"), snapshot("new")])

    assert nodes(changed) == ["new"]
    assert removed == []


def test_a_key_reappearing_after_removal_is_changed_again() -> None:
    tracker = InstanceStateTracker()
    tracker.diff([snapshot("a"), snapshot("b")])
    tracker.diff([snapshot("a")])

    changed, removed = tracker.diff([snapshot("a"), snapshot("b")])

    assert nodes(changed) == ["b"]
    assert removed == []

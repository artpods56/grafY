"""Which instances moved since the last publish, and which vanished (ADR 0020).

Instance state itself is derived from the document, the result store and the
computations in flight, so there is nothing to keep per instance except the
answer that was last sent out. That remembered answer is what turns a full
recomputation into a delta: a snapshot whose key was not seen before, or whose
contents differ, is a change; a key that the recomputation no longer contains is
an instance the document dropped.
"""

from collections.abc import Sequence

from grafy_api.runs.ports import InstanceStateSnapshot
from grafy_core.kernel.instances import InstanceKey


class InstanceStateTracker:
    """The last published snapshot per instance key."""

    def __init__(self) -> None:
        self._published: dict[InstanceKey, InstanceStateSnapshot] = {}

    def diff(
        self,
        snapshots: Sequence[InstanceStateSnapshot],
    ) -> tuple[list[InstanceStateSnapshot], list[InstanceKey]]:
        """What to publish, remembering ``snapshots`` as what was published.

        The first call has nothing remembered, so it reports everything. The
        returned changes follow the order the snapshots were given in, which is
        document order at the caller, not the order keys happen to be remembered.
        """
        current = {snapshot.key: snapshot for snapshot in snapshots}
        changed = [
            snapshot
            for snapshot in snapshots
            if self._published.get(snapshot.key) != snapshot
        ]
        removed = [key for key in self._published if key not in current]
        self._published = current
        return changed, removed

    def forget(self) -> None:
        """Drop what was published, so the next diff reports everything again."""
        self._published = {}

    def current(self) -> list[InstanceStateSnapshot]:
        """What was last published, in the order it was published in."""
        return list(self._published.values())


__all__ = ["InstanceStateTracker"]

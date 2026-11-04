"""The one failure a node computation raises, whatever stage found it."""

from typing import Sequence


class NodeComputationError(RuntimeError):
    """One node instance cannot be computed.

    The scheduler records the message as the last failure of the instance's
    fingerprint, so this text is what a participant sees on a failed node: it
    names the node, its port and the connection at fault, and never a value.
    """


__all__: Sequence[str] = ["NodeComputationError"]

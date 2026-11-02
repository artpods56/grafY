"""What the fingerprint function needs to know that the document cannot say."""

from collections.abc import Mapping
from typing import Protocol

from grafy_core.domain.saved_graphs import SavedGraphNode
from grafy_core.kernel.instances import InstanceKey
from grafy_core.plugins import NodeCachePolicy


class FingerprintFacts(Protocol):
    """Deployment facts, supplied by the application at catalog load."""

    def implementation_digest(self, node: SavedGraphNode) -> str:
        """Opaque digest of the node's implementation identity (hex)."""
        ...

    def cache_policy(self, node: SavedGraphNode) -> NodeCachePolicy: ...

    def secret_revisions(self, key: InstanceKey) -> Mapping[str, str]:
        """Opaque secret revisions the instance runs under, by secret name."""
        ...

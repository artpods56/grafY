from uuid import UUID

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.nodes import UserFacingNodeError
from grafy_core.runtime.execution import NodeRunError

from grafy_api.services.errors import WorkbenchOperationError


class GraphExecutionError(WorkbenchOperationError):
    pass


class ArtifactTypeMismatchError(GraphExecutionError):
    """An input binding carries an artifact type its resolved port does not accept.

    Raised while compiling a run, so it reaches the user before a Plugin sandbox
    is created, and names the port with the accepted and received artifact types
    instead of the generic in-sandbox ``contract_failure``.
    """

    def __init__(
        self,
        message: str,
        *,
        node_id: str,
        port: str,
        expected: tuple[ArtifactTypeKey, ...],
        received: ArtifactTypeKey,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.port = port
        self.expected = expected
        self.received = received


class NestedGraphExecutionError(UserFacingNodeError, GraphExecutionError):
    """A bounded nested-graph failure that is safe at the node seam."""


class SecretContextRequiredError(GraphExecutionError):
    """A secret-bearing node was run without the saved graph that owns its secrets.

    Decided from the submission alone: the node ids are exactly what the caller sent,
    and nothing was loaded to establish that the run cannot proceed. A node's secrets
    are sealed against its saved configuration, so there is no safe reading of the
    request that supplies them implicitly.
    """

    def __init__(self, message: str, *, node_ids: tuple[str, ...]) -> None:
        super().__init__(message)
        self.node_ids = node_ids


class SavedGraphMismatchError(GraphExecutionError):
    """The submitted fragment is not the saved revision it names.

    A run executes what it is given, so anything the saved revision does not contain
    would run work nobody saved. The fields say which part of the fragment differs:
    `node_id` for a single node, and the two counts for an edge or origin multiset,
    which is a multiset so one duplicated edge is not mistaken for two edges.
    """

    def __init__(
        self,
        message: str,
        *,
        graph_id: UUID,
        revision: int,
        node_id: str | None = None,
        missing_count: int | None = None,
        unexpected_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.graph_id = graph_id
        self.revision = revision
        self.node_id = node_id
        self.missing_count = missing_count
        self.unexpected_count = unexpected_count


class SecretBindingError(GraphExecutionError):
    """A secret-bearing node may not spend the secrets its saved identity claims.

    Stored node secrets are sealed against the configuration values the secret was
    declared for, so a submission that keeps the node id while rewriting the
    dependency the credential is keyed on would ask the vault for a secret under
    false pretences. `secret_input` names the declaration when the disagreement is
    with the configuration a particular secret requires.
    """

    def __init__(
        self,
        message: str,
        *,
        node_id: str,
        graph_id: UUID,
        revision: int,
        secret_input: str | None = None,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.graph_id = graph_id
        self.revision = revision
        self.secret_input = secret_input


def render_execution_error(exception: BaseException) -> str:
    """Render public execution context without crossing a node-error seam."""

    rendered: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exception
    while current is not None and id(current) not in seen and len(rendered) < 12:
        seen.add(id(current))
        rendered.append(f"{type(current).__name__}: {current}")
        if isinstance(current, NodeRunError):
            break
        if current.__cause__ is not None:
            current = current.__cause__
            continue
        current = None if current.__suppress_context__ else current.__context__
    return " <- caused by ".join(rendered)


__all__ = [
    "ArtifactTypeMismatchError",
    "GraphExecutionError",
    "NestedGraphExecutionError",
    "SavedGraphMismatchError",
    "SecretBindingError",
    "SecretContextRequiredError",
    "render_execution_error",
]

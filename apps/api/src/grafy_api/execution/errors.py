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
    "render_execution_error",
]

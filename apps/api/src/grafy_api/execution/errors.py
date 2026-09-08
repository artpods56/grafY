from grafy_core.nodes import UserFacingNodeError
from grafy_core.runtime.execution import NodeRunError

from grafy_api.services.errors import WorkbenchOperationError


class GraphExecutionError(WorkbenchOperationError):
    pass


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
    "GraphExecutionError",
    "NestedGraphExecutionError",
    "render_execution_error",
]

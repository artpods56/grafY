"""Progress for code that runs inside a node but is not the node itself.

A Document OCR engine, a chat provider, or a crop recognizer is called from the
node that is on screen. That caller binds its ``NodeExecutionContext`` for the
duration of ``run``. Adapters read it back here and publish the same way a node
does, and a call with no bound context — a unit test, a service built before
the consumer runs — simply does not report.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from inspect import isawaitable

from grafy_core.node_context import NodeExecutionContext

_active_node: ContextVar[NodeExecutionContext | None] = ContextVar(
    "grafy_active_node_context",
    default=None,
)


def active_node_context() -> NodeExecutionContext | None:
    """The node currently inside ``run``, if one has been bound."""

    return _active_node.get()


@asynccontextmanager
async def bind_active_node(
    context: NodeExecutionContext,
) -> AsyncIterator[None]:
    """Publish this node's progress from provider calls it makes."""

    token: Token[NodeExecutionContext | None] = _active_node.set(context)
    try:
        yield
    finally:
        _active_node.reset(token)


async def emit_node_progress(
    context: object | None,
    message: str,
    *,
    current: int | None = None,
    total: int | None = None,
) -> None:
    """Report ``message`` when ``context`` can. A missing context is a no-op.

    A test double that has no ``progress`` method, or a synchronous stand-in,
    must not fail the call. ``NodeExecutionContext.progress`` still validates
    the message and ignores a reporter that itself fails.
    """

    if context is None:
        return
    progress = getattr(context, "progress", None)
    if not callable(progress):
        return
    result = progress(message, current=current, total=total)
    if isawaitable(result):
        await result

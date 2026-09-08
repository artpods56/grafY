"""Top-level execution scope shared by Workspace Plugin sandboxes."""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class PluginSandboxScopeId:
    value: UUID

    @classmethod
    def new(cls) -> "PluginSandboxScopeId":
        return cls(uuid4())


class PluginSandboxLifecycle(Protocol):
    async def close_scope(self, scope_id: PluginSandboxScopeId, /) -> None: ...


_current_scope: ContextVar[PluginSandboxScopeId | None] = ContextVar(
    "grafy_plugin_sandbox_scope",
    default=None,
)


def activate_plugin_sandbox_scope(
    scope_id: PluginSandboxScopeId,
) -> Token[PluginSandboxScopeId | None]:
    return _current_scope.set(scope_id)


def current_plugin_sandbox_scope() -> PluginSandboxScopeId | None:
    return _current_scope.get()


def reset_plugin_sandbox_scope(
    token: Token[PluginSandboxScopeId | None],
) -> None:
    _current_scope.reset(token)


__all__ = [
    "PluginSandboxLifecycle",
    "PluginSandboxScopeId",
    "activate_plugin_sandbox_scope",
    "current_plugin_sandbox_scope",
    "reset_plugin_sandbox_scope",
]

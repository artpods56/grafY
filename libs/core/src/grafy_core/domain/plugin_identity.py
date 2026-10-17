"""Plugin release scope and deployment-owned execution metadata."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PluginReleaseScope(StrEnum):
    """Durable release family scope carried by a Plugin release pin."""

    SYSTEM = "system"
    WORKSPACE = "workspace"


class PluginExecutionPolicy(StrEnum):
    HOST_ELIGIBLE = "host-eligible"
    ISOLATED_ONLY = "isolated-only"


@dataclass(frozen=True, slots=True)
class PlatformPluginActor:
    """Non-secret deployment identity authorized to manage System Plugins."""

    reference: str

    def __post_init__(self) -> None:
        normalized = self.reference.strip()
        if normalized == "" or len(normalized) > 255:
            raise ValueError(
                "Platform Plugin actor reference must contain 1 to 255 characters"
            )
        object.__setattr__(self, "reference", normalized)


@dataclass(frozen=True, slots=True)
class PluginReleaseNamespace:
    """The deployment-owned visibility boundary for every Plugin release."""

    scope: PluginReleaseScope = PluginReleaseScope.SYSTEM
    workspace_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.scope is not PluginReleaseScope.SYSTEM:
            raise ValueError(
                "Plugin releases are visible only in the System namespace"
            )
        if self.workspace_id is not None:
            raise ValueError(
                "System Plugin release namespaces cannot have a Workspace owner"
            )


__all__ = [
    "PlatformPluginActor",
    "PluginExecutionPolicy",
    "PluginReleaseNamespace",
    "PluginReleaseScope",
]

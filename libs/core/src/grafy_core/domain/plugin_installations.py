"""Scoped Plugin installations and their resolved releases."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from grafy_core.domain.plugin_identity import (
    PlatformPluginActor,
    PluginExecutionPolicy,
    PluginReleaseNamespace,
    PluginReleaseScope,
)
from grafy_core.domain.plugin_releases import (
    PluginRelease,
    PluginReleaseError,
)


@dataclass
class PluginInstallation:
    """Append-only assignment of one release to one visibility namespace."""

    release_id: UUID
    scope: PluginReleaseScope
    workspace_id: UUID | None
    slug: str
    release_revision: int
    execution_policy: PluginExecutionPolicy
    installed_by_user_id: UUID | None = None
    installed_by_platform_actor: str | None = None
    installed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        self.scope = PluginReleaseScope(self.scope)
        self.execution_policy = PluginExecutionPolicy(self.execution_policy)
        try:
            PluginReleaseNamespace(
                scope=self.scope,
                workspace_id=self.workspace_id,
            )
        except ValueError as exc:
            raise PluginReleaseError(str(exc)) from exc
        if self.scope is PluginReleaseScope.SYSTEM:
            if self.installed_by_user_id is not None:
                raise PluginReleaseError(
                    "System Plugin installations cannot use a Workspace user actor"
                )
            if self.installed_by_platform_actor is None:
                raise PluginReleaseError(
                    "System Plugin installations require a platform actor"
                )
            try:
                actor = PlatformPluginActor(self.installed_by_platform_actor)
            except ValueError as exc:
                raise PluginReleaseError(str(exc)) from exc
            self.installed_by_platform_actor = actor.reference
        else:
            if self.installed_by_user_id is None:
                raise PluginReleaseError(
                    "Workspace Plugin installations require a Workspace user actor"
                )
            if self.installed_by_platform_actor is not None:
                raise PluginReleaseError(
                    "Workspace Plugin installations cannot use a platform actor"
                )
            if self.execution_policy is not PluginExecutionPolicy.ISOLATED_ONLY:
                raise PluginReleaseError(
                    "Workspace Plugin installations must use isolated-only execution"
                )
        if self.slug.strip() == "" or len(self.slug) > 100:
            raise PluginReleaseError(
                "Plugin installation slug must contain 1 to 100 characters"
            )
        if isinstance(self.release_revision, bool) or self.release_revision < 1:
            raise PluginReleaseError(
                "Plugin installation release revision must be positive"
            )
        if self.installed_at.tzinfo is None:
            raise PluginReleaseError("Plugin installed_at must be timezone-aware")

    @classmethod
    def from_release(
        cls,
        release: PluginRelease,
        *,
        namespace: PluginReleaseNamespace,
        execution_policy: PluginExecutionPolicy,
        installed_by_user_id: UUID | None,
        installed_by_platform_actor: str | None,
    ) -> "PluginInstallation":
        return cls(
            release_id=release.id,
            scope=namespace.scope,
            workspace_id=namespace.workspace_id,
            slug=release.slug,
            release_revision=release.revision,
            execution_policy=execution_policy,
            installed_by_user_id=installed_by_user_id,
            installed_by_platform_actor=installed_by_platform_actor,
        )

    @property
    def namespace(self) -> PluginReleaseNamespace:
        return PluginReleaseNamespace(
            scope=self.scope,
            workspace_id=self.workspace_id,
        )


@dataclass(frozen=True, slots=True)
class InstalledPluginRelease:
    """One immutable release resolved through an exact scoped installation."""

    release: PluginRelease
    installation: PluginInstallation

    def __post_init__(self) -> None:
        if (
            self.installation.release_id != self.release.id
            or self.installation.slug != self.release.slug
            or self.installation.release_revision != self.release.revision
        ):
            raise PluginReleaseError(
                "Plugin installation does not match its immutable release"
            )

    @property
    def descriptor_digest(self) -> str:
        if self.release.descriptor_digest is None:
            raise PluginReleaseError("Plugin release has no descriptor digest")
        return self.release.descriptor_digest


__all__ = ["InstalledPluginRelease", "PluginInstallation"]

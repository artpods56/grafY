"""Mutable catalog selection kept separate from immutable Plugin releases."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from grafy_core.domain.plugin_identity import (
    PluginReleaseNamespace,
    PluginReleaseScope,
)
from grafy_core.domain.plugin_installations import InstalledPluginRelease


class PluginFamilyLifecycle(StrEnum):
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    WITHDRAWN = "withdrawn"


class PluginReleaseSelectionError(ValueError):
    """A mutable Plugin family selection would violate its release identity."""


@dataclass
class PluginReleaseSelection:
    """Exact selected release and mutable catalog state for one Plugin family."""

    scope: PluginReleaseScope
    workspace_id: UUID | None
    slug: str
    selected_release_id: UUID
    selected_revision: int
    lifecycle: PluginFamilyLifecycle = PluginFamilyLifecycle.PUBLISHED
    generation: int = 1
    id: UUID = field(default_factory=uuid4)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by_actor: str | None = None

    def __post_init__(self) -> None:
        self.scope = PluginReleaseScope(self.scope)
        self.lifecycle = PluginFamilyLifecycle(self.lifecycle)
        PluginReleaseNamespace(scope=self.scope, workspace_id=self.workspace_id)
        self.slug = self.slug.strip()
        if self.slug == "" or len(self.slug) > 100:
            raise PluginReleaseSelectionError(
                "Plugin release selection slug must contain 1 to 100 characters"
            )
        if isinstance(self.selected_revision, bool) or self.selected_revision < 1:
            raise PluginReleaseSelectionError(
                "Plugin selected revision must be a positive integer"
            )
        if isinstance(self.generation, bool) or self.generation < 1:
            raise PluginReleaseSelectionError(
                "Plugin selection generation must be a positive integer"
            )
        if self.updated_at.tzinfo is None:
            raise PluginReleaseSelectionError(
                "Plugin selection updated_at must be timezone-aware"
            )
        if self.updated_by_actor is not None:
            actor = self.updated_by_actor.strip()
            if actor == "" or len(actor) > 255:
                raise PluginReleaseSelectionError(
                    "Plugin selection actor must contain 1 to 255 characters"
                )
            self.updated_by_actor = actor

    @classmethod
    def from_release(
        cls,
        release: InstalledPluginRelease,
        *,
        actor_reference: str | None = None,
    ) -> "PluginReleaseSelection":
        return cls(
            scope=release.installation.scope,
            workspace_id=release.installation.workspace_id,
            slug=release.release.slug,
            selected_release_id=release.release.id,
            selected_revision=release.release.revision,
            updated_by_actor=actor_reference,
        )

    @property
    def namespace(self) -> PluginReleaseNamespace:
        return PluginReleaseNamespace(
            scope=self.scope,
            workspace_id=self.workspace_id,
        )

    @property
    def allows_new_insertion(self) -> bool:
        return self.lifecycle is PluginFamilyLifecycle.PUBLISHED

    def select(
        self,
        release: InstalledPluginRelease,
        *,
        publish: bool = False,
        when: datetime | None = None,
        actor_reference: str | None = None,
    ) -> None:
        if (
            release.installation.namespace != self.namespace
            or release.release.slug != self.slug
        ):
            raise PluginReleaseSelectionError(
                "Selected Plugin release must belong to the same scoped family"
            )
        next_lifecycle = PluginFamilyLifecycle.PUBLISHED if publish else self.lifecycle
        if (
            self.selected_release_id == release.release.id
            and self.selected_revision == release.release.revision
            and self.lifecycle is next_lifecycle
        ):
            return
        changed_at = when or datetime.now(UTC)
        if changed_at.tzinfo is None:
            raise PluginReleaseSelectionError(
                "Plugin selection updated_at must be timezone-aware"
            )
        if actor_reference is not None:
            actor_reference = actor_reference.strip()
            if actor_reference == "" or len(actor_reference) > 255:
                raise PluginReleaseSelectionError(
                    "Plugin selection actor must contain 1 to 255 characters"
                )
        self.selected_release_id = release.release.id
        self.selected_revision = release.release.revision
        self.lifecycle = next_lifecycle
        self.generation += 1
        self.updated_at = changed_at
        self.updated_by_actor = actor_reference

    def deprecate(self, *, when: datetime | None = None) -> None:
        if self.lifecycle is PluginFamilyLifecycle.WITHDRAWN:
            raise PluginReleaseSelectionError(
                "Withdrawn Plugin families cannot be deprecated"
            )
        if self.lifecycle is PluginFamilyLifecycle.DEPRECATED:
            return
        changed_at = when or datetime.now(UTC)
        if changed_at.tzinfo is None:
            raise PluginReleaseSelectionError(
                "Plugin selection updated_at must be timezone-aware"
            )
        self.lifecycle = PluginFamilyLifecycle.DEPRECATED
        self.generation += 1
        self.updated_at = changed_at

    def withdraw(self, *, when: datetime | None = None) -> None:
        if self.lifecycle is PluginFamilyLifecycle.WITHDRAWN:
            return
        changed_at = when or datetime.now(UTC)
        if changed_at.tzinfo is None:
            raise PluginReleaseSelectionError(
                "Plugin selection updated_at must be timezone-aware"
            )
        self.lifecycle = PluginFamilyLifecycle.WITHDRAWN
        self.generation += 1
        self.updated_at = changed_at


__all__ = [
    "PluginFamilyLifecycle",
    "PluginReleaseSelection",
    "PluginReleaseSelectionError",
]

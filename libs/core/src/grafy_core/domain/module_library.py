"""Workspace module library aggregate (publish a release)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ModulePublicationState(StrEnum):
    """Publication state of a stored Module.

    Only `published` is reachable now. `deprecated` and `withdrawn` remain so rows
    written before the lifecycle was cut still load, and stay hidden from browse.
    """

    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    WITHDRAWN = "withdrawn"


class ModuleLibraryError(ValueError):
    """Raised when a module library invariant would be violated."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_nonempty(value: str, label: str, maximum: int) -> str:
    stripped = value.strip()
    if stripped == "":
        raise ModuleLibraryError(f"{label} must not be blank")
    if len(stripped) > maximum:
        raise ModuleLibraryError(f"{label} must be at most {maximum} characters")
    return stripped


@dataclass
class ModuleRelease:
    workspace_id: UUID
    module_id: UUID
    revision: int
    source_graph_id: UUID
    published_at: datetime = field(default_factory=_utc_now)
    published_by_user_id: UUID | None = None

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or self.revision < 1:
            raise ModuleLibraryError(
                "Module release revision must be a positive integer"
            )
        if self.published_at.tzinfo is None:
            raise ModuleLibraryError(
                "Module release published_at must be timezone-aware"
            )


@dataclass
class Module:
    """Reusable building block hosted by a workspace library."""

    workspace_id: UUID
    source_graph_id: UUID
    name: str
    description: str | None = None
    publication_state: ModulePublicationState = ModulePublicationState.PUBLISHED
    current_library_release: int | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.name = _require_nonempty(self.name, "Module name", 160)
        if self.description is not None:
            description = self.description.strip()
            if description == "":
                raise ModuleLibraryError("Module description must not be blank")
            if len(description) > 1000:
                raise ModuleLibraryError(
                    "Module description must be at most 1000 characters"
                )
            self.description = description
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ModuleLibraryError("Module timestamps must be timezone-aware")
        if self.current_library_release is not None and (
            isinstance(self.current_library_release, bool)
            or self.current_library_release < 1
        ):
            raise ModuleLibraryError(
                "Module current_library_release must be a positive integer"
            )

    def touch(self, *, when: datetime | None = None) -> None:
        self.updated_at = when or _utc_now()

    def apply_publish(
        self,
        *,
        revision: int,
        name: str | None = None,
        description: str | None = None,
        when: datetime | None = None,
    ) -> None:
        if isinstance(revision, bool) or revision < 1:
            raise ModuleLibraryError("Published revision must be a positive integer")
        if name is not None:
            self.name = _require_nonempty(name, "Module name", 160)
        if description is not None:
            if description.strip() == "":
                self.description = None
            else:
                self.description = _require_nonempty(
                    description, "Module description", 1000
                )
        self.publication_state = ModulePublicationState.PUBLISHED
        self.current_library_release = revision
        self.touch(when=when)


__all__ = [
    "Module",
    "ModuleLibraryError",
    "ModulePublicationState",
    "ModuleRelease",
]

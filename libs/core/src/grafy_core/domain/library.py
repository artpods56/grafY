"""The Workspace Library folder tree the user owns.

A Library folder is a row in a tree the workspace created: folders nest to any
depth, an artifact either sits inside one of them or sits at the root, and
nothing about the shape is derived from the artifact's type. The rules a
signature cannot carry — no cycles, no duplicate sibling names, deleting only an
empty folder — are errors raised by the service that owns them.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

_MAX_FOLDER_NAME_LENGTH = 160
# Unicode's widest casefolding turns one character into three: U+0390 GREEK SMALL
# LETTER IOTA WITH DIALYTIKA AND TONOS folds to iota + combining diaeresis +
# combining acute. A name at the length limit therefore keys to three times its
# length, and the sibling-uniqueness column has to hold that or a valid name 500s.
_MAX_CASEFOLD_EXPANSION = 3
MAX_FOLDER_NAME_KEY_LENGTH = _MAX_FOLDER_NAME_LENGTH * _MAX_CASEFOLD_EXPANSION


def _validated_folder_name(value: str) -> str:
    name = value.strip()
    if name == "":
        raise ValueError("Library folder name must not be blank")
    if len(name) > _MAX_FOLDER_NAME_LENGTH:
        raise ValueError(
            f"Library folder name must be at most {_MAX_FOLDER_NAME_LENGTH} characters"
        )
    return name


@dataclass
class LibraryFolder:
    """One directory of the Library tree. ``parent_id`` of ``None`` is the root."""

    workspace_id: UUID
    name: str
    parent_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.name = _validated_folder_name(self.name)
        if self.parent_id == self.id:
            raise ValueError("Library folder cannot be its own parent")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Library folder timestamps must be timezone-aware")

    @property
    def name_key(self) -> str:
        """The sibling-uniqueness key: names differ only by case or padding."""
        return self.name.casefold()

    def rename(self, name: str, *, updated_at: datetime | None = None) -> None:
        replacement_time = updated_at or datetime.now(UTC)
        if replacement_time.tzinfo is None:
            raise ValueError("Library folder timestamps must be timezone-aware")
        self.name = _validated_folder_name(name)
        self.updated_at = replacement_time

    def move_to(
        self,
        parent_id: UUID | None,
        *,
        updated_at: datetime | None = None,
    ) -> None:
        replacement_time = updated_at or datetime.now(UTC)
        if replacement_time.tzinfo is None:
            raise ValueError("Library folder timestamps must be timezone-aware")
        if parent_id == self.id:
            raise ValueError("Library folder cannot be its own parent")
        self.parent_id = parent_id
        self.updated_at = replacement_time


def is_descendant_folder(
    folders: Sequence[LibraryFolder],
    *,
    candidate_id: UUID,
    ancestor_id: UUID,
) -> bool:
    """Whether ``candidate_id`` is ``ancestor_id`` itself or sits beneath it.

    The caller passes the workspace's folders, which is the whole tree the panel
    already reads. A walk stops at a parent that is not in the sequence, so a
    stale read cannot report a cycle the stored tree does not have; the ``seen``
    set keeps a database that somehow holds a cycle terminating anyway.
    """
    by_id = {folder.id: folder for folder in folders}
    seen: set[UUID] = set()
    current: UUID | None = candidate_id
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        _ = seen.add(current)
        folder = by_id.get(current)
        current = None if folder is None else folder.parent_id
    return False


__all__ = ["MAX_FOLDER_NAME_KEY_LENGTH", "LibraryFolder", "is_descendant_folder"]

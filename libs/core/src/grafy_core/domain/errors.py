import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


_FAILURE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_MAX_FAILURE_CODE_LENGTH = 120
# The limits behind ``_listed_graph_titles``. Three names of forty characters plus
# the count of the rest stays inside ``_MAX_PUBLIC_MESSAGE_LENGTH`` with room for
# the sentence in front of it.
_MAX_LISTED_TITLES = 3
_MAX_LISTED_TITLE_LENGTH = 40
_MAX_PUBLIC_DETAIL_LENGTH = 160
_MAX_PUBLIC_MESSAGE_LENGTH = 200


class FailureKind(StrEnum):
    VALIDATION = "validation"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    CAPACITY = "capacity"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class FailureSpec:
    code: str
    kind: FailureKind
    public_message: str

    def __post_init__(self) -> None:
        if len(self.code) > _MAX_FAILURE_CODE_LENGTH:
            raise ValueError(
                f"Failure code must be at most {_MAX_FAILURE_CODE_LENGTH} characters"
            )
        if _FAILURE_CODE_PATTERN.fullmatch(self.code) is None:
            raise ValueError("Failure code must be a lowercase namespaced identifier")
        if self.public_message.strip() == "":
            raise ValueError("Failure public message must not be blank")
        if len(self.public_message) > _MAX_PUBLIC_MESSAGE_LENGTH:
            raise ValueError(
                "Failure public message must be at most "
                f"{_MAX_PUBLIC_MESSAGE_LENGTH} characters"
            )


class Failure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    error_id: UUID
    code: str = Field(
        min_length=3,
        max_length=_MAX_FAILURE_CODE_LENGTH,
        pattern=_FAILURE_CODE_PATTERN.pattern,
    )
    kind: FailureKind
    message: str = Field(min_length=1, max_length=_MAX_PUBLIC_MESSAGE_LENGTH)


class GrafyCoreError(Exception):
    """Base application error."""

    failure_spec: ClassVar[FailureSpec | None] = None

    @property
    def public_message(self) -> str | None:
        if self.failure_spec is None:
            return None
        return self.failure_spec.public_message

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {}


class NotFoundError(GrafyCoreError):
    """A requested resource was not found."""

    failure_spec = FailureSpec(
        code="resource.not_found",
        kind=FailureKind.NOT_FOUND,
        public_message="Not found",
    )

    def __init__(self, resource: str, resource_id: str) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} not found: {resource_id}")

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {"resource": self.resource}

class ValidationError(GrafyCoreError):
    "Raised during validation."

    failure_spec = FailureSpec(
        code="validation.error",
        kind=FailureKind.VALIDATION,
        public_message="Validation error",
    )


class ObjectAlreadyExistsError(GrafyCoreError):
    """Raised when an object already exists in the storage backend."""

    failure_spec = FailureSpec(
        code="resource.already_exists",
        kind=FailureKind.CONFLICT,
        public_message="The resource already exists",
    )


class ConcurrentWriteError(GrafyCoreError):
    """Raised when persistence detects an optimistic concurrency conflict."""

    failure_spec = FailureSpec(
        code="persistence.concurrent_write",
        kind=FailureKind.CONFLICT,
        public_message="The resource changed during this operation",
    )


class IdentityInvariantError(GrafyCoreError):
    """Raised when an identity or workspace invariant would be violated."""

    failure_spec = FailureSpec(
        code="identity.invariant",
        kind=FailureKind.CONFLICT,
        public_message="Identity operation failed",
    )


class LastWorkspaceOwnerError(IdentityInvariantError):
    """Raised when an operation would remove the last active workspace owner."""


class UserDisabledError(IdentityInvariantError):
    """Raised when a disabled user attempts to authenticate or authorize."""

    failure_spec = FailureSpec(
        code="identity.user_disabled",
        kind=FailureKind.UNAUTHENTICATED,
        public_message="Authentication required",
    )


class CredentialAuthenticationError(IdentityInvariantError):
    """Raised when a bearer credential cannot authenticate a principal."""

    def __init__(self) -> None:
        super().__init__("Credential is invalid, expired, or revoked")


class CapabilityDeniedError(IdentityInvariantError):
    """Raised when an active membership lacks one required capability."""

    failure_spec = FailureSpec(
        code="identity.capability_denied",
        kind=FailureKind.FORBIDDEN,
        public_message="Forbidden",
    )

    def __init__(self, *, capability: str, workspace_id: UUID, user_id: UUID) -> None:
        self.capability = capability
        self.workspace_id = workspace_id
        self.user_id = user_id
        super().__init__(
            f"User {user_id} is not authorized for capability {capability!r} "
            f"in workspace {workspace_id}"
        )

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {
            "capability": self.capability,
            "workspace_id": self.workspace_id,
            "actor_id": self.user_id,
        }


class SavedGraphRevisionConflictError(GrafyCoreError):
    failure_spec = FailureSpec(
        code="graph.revision_conflict",
        kind=FailureKind.CONFLICT,
        public_message="The graph changed while it was being saved",
    )

    def __init__(
        self,
        *,
        graph_id: UUID,
        expected_revision: int,
        actual_revision: int | None,
    ) -> None:
        self.graph_id = graph_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        if actual_revision is None:
            detail = "the graph changed while it was being saved"
        else:
            detail = f"the current revision is {actual_revision}"
        super().__init__(
            f"Saved graph {graph_id} revision conflict: expected "
            f"{expected_revision}, but {detail}"
        )

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {
            "graph_id": self.graph_id,
            "expected_revision": self.expected_revision,
            "actual_revision": self.actual_revision,
        }


class GraphFolderNameConflictError(GrafyCoreError):
    """Raised when one workspace already has a folder with the requested name."""

    failure_spec = FailureSpec(
        code="graph.folder_name_conflict",
        kind=FailureKind.CONFLICT,
        public_message="A graph folder with this name already exists",
    )

    def __init__(self, *, workspace_id: UUID, name: str) -> None:
        self.workspace_id = workspace_id
        self.name = name
        super().__init__(
            f"Graph folder name {name!r} is already in use in workspace {workspace_id}"
        )


class LibraryFolderNameConflictError(GrafyCoreError):
    """Raised when another Library folder in the same parent has the name."""

    failure_spec = FailureSpec(
        code="library.folder_name_conflict",
        kind=FailureKind.CONFLICT,
        public_message="A folder with this name already exists here",
    )

    def __init__(
        self,
        *,
        workspace_id: UUID,
        parent_id: UUID | None,
        name: str,
    ) -> None:
        self.workspace_id = workspace_id
        self.parent_id = parent_id
        self.name = name
        super().__init__(
            f"Library folder name {name!r} is already in use in workspace "
            f"{workspace_id} under parent {parent_id}"
        )

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "parent_id": self.parent_id,
            "name": self.name,
        }


class LibraryArtifactInUseError(GrafyCoreError):
    """Raised when a Library artifact is still referenced by saved work.

    A reference lives in a saved graph revision or in execution history, and both
    outlive the run that made them, so dropping the artifact would leave a
    dangling reference the user only meets later as a failed load. The refusal
    names the graphs that hold it. Taking it anyway means the glossary's forced
    delete, which rewrites each referencing graph's head revision and leaves the
    input unsatisfied; that is not implemented, so the paths open today are to
    unfile the artifact, which keeps it, or to delete the referencing graph.
    """

    failure_spec = FailureSpec(
        code="library.artifact_in_use",
        kind=FailureKind.CONFLICT,
        public_message="This Library artifact is still used by saved work",
    )

    def __init__(
        self,
        *,
        artifact_id: UUID,
        graph_ids: Sequence[UUID],
        graph_titles: Sequence[str],
    ) -> None:
        self.artifact_id = artifact_id
        self.graph_ids = tuple(graph_ids)
        self.graph_titles = tuple(graph_titles)
        super().__init__(
            (
                f"Library artifact {artifact_id} is referenced by "
                f"{len(self.graph_titles)} saved graph(s): "
                f"{', '.join(self.graph_titles)}"
            )
        )

    @property
    def public_message(self) -> str:
        return f"Still used by: {_listed_graph_titles(self.graph_titles)}"

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {"artifact_id": self.artifact_id, "graph_ids": self.graph_ids}


def _listed_graph_titles(graph_titles: Sequence[str]) -> str:
    """Name the referencing graphs within the public detail budget.

    A Library folder name reaches 160 characters and several graphs can hold the
    same reference, so the listing is clipped: the first few names in full, the
    rest counted. The whole string stays under the 200-character limit
    ``FailureSpec`` places on ``Failure.message``.
    """

    shown = [_clipped_graph_title(title) for title in graph_titles[:_MAX_LISTED_TITLES]]
    omitted = len(graph_titles) - len(shown)
    if omitted > 0:
        shown.append(f"and {omitted} more")
    return ", ".join(shown)[:_MAX_PUBLIC_DETAIL_LENGTH]


def _clipped_graph_title(title: str) -> str:
    if len(title) <= _MAX_LISTED_TITLE_LENGTH:
        return title
    return f"{title[: _MAX_LISTED_TITLE_LENGTH - 1]}…"


class LibraryFolderNotEmptyError(GrafyCoreError):
    """Raised when a Library folder still holds artifacts or child folders."""

    failure_spec = FailureSpec(
        code="library.folder_not_empty",
        kind=FailureKind.CONFLICT,
        public_message="Move the contents out before deleting this folder",
    )

    def __init__(
        self,
        *,
        folder_id: UUID,
        artifact_count: int,
        child_count: int,
    ) -> None:
        self.folder_id = folder_id
        self.artifact_count = artifact_count
        self.child_count = child_count
        super().__init__(
            f"Library folder {folder_id} holds {artifact_count} artifact(s) and "
            f"{child_count} folder(s)"
        )

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {
            "folder_id": self.folder_id,
            "artifact_count": self.artifact_count,
            "child_count": self.child_count,
        }


class LibraryFolderCycleError(GrafyCoreError):
    """Raised when a Library folder would become a descendant of itself."""

    failure_spec = FailureSpec(
        code="library.folder_cycle",
        kind=FailureKind.VALIDATION,
        public_message="A folder cannot be moved inside itself",
    )

    def __init__(self, *, folder_id: UUID, parent_id: UUID) -> None:
        self.folder_id = folder_id
        self.parent_id = parent_id
        super().__init__(
            f"Library folder {folder_id} cannot be moved inside itself "
            f"(parent {parent_id})"
        )

    @property
    def diagnostic_context(self) -> Mapping[str, object]:
        return {"folder_id": self.folder_id, "parent_id": self.parent_id}


class CollaborationError(GrafyCoreError):
    """Base error for collaborative head and command workflows."""

    error_code: str = "collaboration_error"


class MissingCollaborativeHeadError(CollaborationError):
    error_code = "missing_collaborative_head"

    def __init__(self, *, workspace_id: UUID, graph_id: UUID) -> None:
        self.workspace_id = workspace_id
        self.graph_id = graph_id
        super().__init__(
            f"Collaborative head missing for graph {graph_id} in workspace "
            f"{workspace_id}"
        )


class CollaborationHeadConflictError(CollaborationError):
    error_code = "head_moved"

    def __init__(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        expected_sequence: int,
        actual_sequence: int,
        room_epoch: UUID,
    ) -> None:
        self.workspace_id = workspace_id
        self.graph_id = graph_id
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence
        self.room_epoch = room_epoch
        super().__init__(
            f"Collaborative head for graph {graph_id} moved: expected sequence "
            f"{expected_sequence}, actual {actual_sequence}"
        )


class CollaborationIdempotencyMismatchError(CollaborationError):
    error_code = "idempotency_mismatch"

    def __init__(self, *, workspace_id: UUID, graph_id: UUID, command_id: UUID) -> None:
        self.workspace_id = workspace_id
        self.graph_id = graph_id
        self.command_id = command_id
        super().__init__(
            f"Command id {command_id} was reused with a different payload for "
            f"graph {graph_id} in workspace {workspace_id}"
        )


class CollaborationCommandRejectedError(CollaborationError):
    error_code = "command_rejected"

    def __init__(self, *, code: str, message: str) -> None:
        self.error_code = code
        super().__init__(message)


class CollaborationUncheckpointedError(CollaborationError):
    error_code = "uncheckpointed_head"

    def __init__(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        head_sequence: int,
        checkpoint_sequence: int,
    ) -> None:
        self.workspace_id = workspace_id
        self.graph_id = graph_id
        self.head_sequence = head_sequence
        self.checkpoint_sequence = checkpoint_sequence
        super().__init__(
            f"Collaborative head for graph {graph_id} has uncheckpointed "
            f"commands at sequence {head_sequence} "
            f"(checkpointed through {checkpoint_sequence})"
        )


class CollaborationActiveExecutionError(CollaborationError):
    error_code = "active_execution"

    def __init__(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        execution_id: UUID,
    ) -> None:
        self.workspace_id = workspace_id
        self.graph_id = graph_id
        self.execution_id = execution_id
        super().__init__(
            f"Graph {graph_id} in workspace {workspace_id} has active execution "
            f"{execution_id}"
        )

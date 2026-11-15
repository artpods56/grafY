from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from typing import Final, Protocol
from uuid import UUID

from grafy_core.artifacts import ArtifactTypeKey


MAX_NODE_PROGRESS_MESSAGE_LENGTH: Final = 1_000
MAX_NODE_PROGRESS_COUNTER: Final = 9_007_199_254_740_991
MAX_NODE_ERROR_MESSAGE_LENGTH: Final = 1_000


class UserFacingNodeError(RuntimeError):
    """An operator failure whose bounded message is safe to show to graph users.

    Raising this exception is an explicit assertion by Plugin code that the
    message contains no credentials, prompts, provider response bodies, or other
    sensitive runtime state. Unknown exceptions remain private implementation
    failures and cross runtime adapters only as a generic error.
    """

    def __init__(self, message: str) -> None:
        normalized = message.strip()
        if normalized == "":
            raise ValueError("User-facing node error message must not be blank")
        if len(normalized) > MAX_NODE_ERROR_MESSAGE_LENGTH:
            raise ValueError(
                "User-facing node error message must be at most "
                f"{MAX_NODE_ERROR_MESSAGE_LENGTH} characters"
            )
        super().__init__(normalized)


class NodeProgressReporter(Protocol):
    """Host boundary for ephemeral, user-visible node progress."""

    async def report_progress(
        self,
        context: "NodeExecutionContext",
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class NodeExecutionContext:
    """Where one node instance runs, in Project vocabulary (ADR 0020).

    ``graph_id`` and ``node_id`` name the instance inside the Graph it belongs to,
    ``call_path`` the call nodes entered to reach that Graph, and ``fingerprint``
    the digest its result is stored under. An operator that needs a stable
    identity of its own has that fingerprint, not a per-run identifier: runs are
    demands for fresh results and never own one.
    """

    workspace_id: UUID
    project_id: UUID | None = None
    graph_id: str | None = None
    node_id: str | None = None
    call_path: tuple[str, ...] = ()
    fingerprint: str | None = None
    invocation_index: int | None = None
    invocation_path: tuple[int, ...] = ()
    artifact_type_bindings: Mapping[str, ArtifactTypeKey] = dataclass_field(
        default_factory=dict[str, ArtifactTypeKey],
        repr=False,
        compare=False,
    )
    progress_reporter: NodeProgressReporter | None = dataclass_field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_path", tuple(self.call_path))
        object.__setattr__(self, "invocation_path", tuple(self.invocation_path))

    async def progress(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        """Publish bounded progress text without exposing node inputs or config."""

        normalized_message = message.strip()
        if normalized_message == "":
            raise ValueError("Node progress message must not be blank")
        if len(normalized_message) > MAX_NODE_PROGRESS_MESSAGE_LENGTH:
            raise ValueError(
                "Node progress message must be at most "
                f"{MAX_NODE_PROGRESS_MESSAGE_LENGTH} characters"
            )
        if current is not None and current < 0:
            raise ValueError("Node progress current value must not be negative")
        if current is not None and current > MAX_NODE_PROGRESS_COUNTER:
            raise ValueError(
                "Node progress current value must not exceed "
                f"{MAX_NODE_PROGRESS_COUNTER}"
            )
        if total is not None and total < 0:
            raise ValueError("Node progress total value must not be negative")
        if total is not None and total > MAX_NODE_PROGRESS_COUNTER:
            raise ValueError(
                f"Node progress total value must not exceed {MAX_NODE_PROGRESS_COUNTER}"
            )
        if current is not None and total is not None and current > total:
            raise ValueError("Node progress current value must not exceed total")

        reporter = self.progress_reporter
        if reporter is None:
            return
        try:
            await reporter.report_progress(
                self,
                normalized_message,
                current=current,
                total=total,
            )
        except Exception:
            # User-visible reporting is best-effort. Reporter failures must not
            # turn a successful node action into a failed graph execution.
            return

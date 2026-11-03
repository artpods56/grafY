"""Seams between the Run service and the rest of the API application.

``RunService`` (``service.py``) depends on these protocols only. Composition
wires the real adapters; tests wire fakes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from grafy_core.domain.runs import Run
from grafy_core.kernel.facts import FingerprintFacts
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.project import ProjectDocument
from grafy_core.kernel.results import ResultStore
from grafy_core.kernel.scheduler import ComputationRunner
from grafy_core.kernel.state import InstanceState


class RunRejectedError(ValueError):
    """A Run cannot be started or a request names something that does not exist.

    ``code`` is a stable machine-readable slug: ``unknown_graph``,
    ``unknown_target``, ``unknown_operator``, ``invalid_document``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RunNotFoundError(LookupError):
    """No Run with that id in that Project."""


class ProjectDocumentSource(Protocol):
    """Reads the live head document. Raises ``NotFoundError`` for a missing Project."""

    async def head_document(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectDocument: ...


@dataclass(frozen=True, slots=True)
class InstanceStateSnapshot:
    key: InstanceKey
    state: InstanceState
    fingerprint: str
    last_result_fingerprint: str | None = None
    error: str | None = None


class RunEvents(Protocol):
    """Outbound notifications. The room hub adapter implements this.

    Implementations must not raise into the scheduler: a failed fan-out is
    logged by the adapter, never propagated.
    """

    async def run_started(self, run: Run) -> None: ...

    async def run_finished(self, run: Run) -> None: ...

    async def instances_changed(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        changed: Sequence[InstanceStateSnapshot],
        removed: Sequence[InstanceKey],
    ) -> None: ...


class FingerprintFactsFactory(Protocol):
    """Builds the sync ``FingerprintFacts`` for one document.

    Async because secret revisions come from the database. ``cache_policy`` of
    an operator this build does not register must raise
    ``RunRejectedError("unknown_operator", ...)``; it never answers ``NEVER``.
    """

    async def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        document: ProjectDocument,
    ) -> FingerprintFacts: ...


class ComputationRunnerFactory(Protocol):
    """Builds the kernel ``ComputationRunner`` for one Project.

    ``store`` is the Workspace-bound result store; the runner reads upstream
    outputs from it by fingerprint and never writes it (the scheduler does).
    """

    def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: ResultStore,
    ) -> ComputationRunner: ...

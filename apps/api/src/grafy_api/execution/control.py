"""Cooperative cancellation and outer-node progress for one graph execution."""

import asyncio
from typing import Protocol
from uuid import UUID

from grafy_core.nodes import NodeExecutionContext, NodeProgressReporter

from grafy_api.execution.events import (
    NodeExecutionEventStatus,
    RunExecutionStatus,
)


class RunExecutionEventReporter(NodeProgressReporter, Protocol):
    """Runtime-facing portion of one managed execution's event journal."""

    def publish_execution_status(
        self,
        status: RunExecutionStatus,
        active_node_id: str | None,
        /,
    ) -> None: ...

    def publish_node_status(
        self,
        *,
        status: NodeExecutionEventStatus,
        node_path: tuple[str, ...],
        node_id: str,
        node_run_id: UUID | None,
        invocation_index: int | None,
        invocation_path: tuple[int, ...],
    ) -> None: ...


class RunExecutionCancelled(asyncio.CancelledError):
    """Raised when a managed graph execution observes cancellation intent."""


class RunExecutionControl:
    """Mutable, in-process control shared by one top-level execution tree."""

    def __init__(
        self,
        event_reporter: RunExecutionEventReporter | None = None,
        /,
    ) -> None:
        self._cancel_requested = False
        self._active_node_id: str | None = None
        self._event_reporter = event_reporter

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    @property
    def active_node_id(self) -> str | None:
        return self._active_node_id

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def check_cancelled(self) -> None:
        if self._cancel_requested:
            raise RunExecutionCancelled("Graph execution was cancelled")

    def start_outer_node(self, node_id: str) -> None:
        self.check_cancelled()
        self._active_node_id = node_id

    def finish_outer_node(self, node_id: str) -> None:
        if self._active_node_id == node_id:
            self._active_node_id = None

    def publish_execution_status(
        self,
        status: RunExecutionStatus,
        active_node_id: str | None,
        /,
    ) -> None:
        reporter = self._event_reporter
        if reporter is not None:
            try:
                reporter.publish_execution_status(status, active_node_id)
            except Exception:
                return

    def publish_node_status(
        self,
        *,
        status: NodeExecutionEventStatus,
        node_path: tuple[str, ...],
        node_id: str,
        node_run_id: UUID | None,
        invocation_index: int | None = None,
        invocation_path: tuple[int, ...] = (),
    ) -> None:
        reporter = self._event_reporter
        if reporter is not None:
            try:
                reporter.publish_node_status(
                    status=status,
                    node_path=node_path,
                    node_id=node_id,
                    node_run_id=node_run_id,
                    invocation_index=invocation_index,
                    invocation_path=invocation_path,
                )
            except Exception:
                return

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        reporter = self._event_reporter
        if reporter is not None:
            try:
                await reporter.report_progress(
                    context,
                    message,
                    current=current,
                    total=total,
                )
            except Exception:
                return


__all__ = [
    "RunExecutionCancelled",
    "RunExecutionControl",
    "RunExecutionEventReporter",
]

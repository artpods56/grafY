"""Feedback reports: anyone signed in sends one, operators triage them.

A report is about the app, not about Workspace data, so it belongs to the
deployment. The routes decide who may call what: sending needs a browser
session, everything else needs operator authority.
"""

import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.feedback import (
    FeedbackClient,
    FeedbackElement,
    FeedbackKind,
    FeedbackRateLimitedError,
    FeedbackReport,
    FeedbackScreenshot,
    FeedbackScreenshotError,
    FeedbackStatus,
)
from grafy_core.domain.identity import ActorContext, User, Workspace
from grafy_core.ports.feedback import FeedbackUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand

MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
REPORTS_PER_HOUR = 20

# Content type -> (leading bytes, stored file extension).
_SCREENSHOT_FORMATS = {
    "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
    "image/jpeg": (b"\xff\xd8\xff", "jpg"),
}


@dataclass(frozen=True, slots=True)
class FeedbackReportView:
    """A report with the people and Workspace an operator reads it by."""

    report: FeedbackReport
    reporter: User | None
    workspace: Workspace | None


class FeedbackService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], FeedbackUnitOfWorkPort],
        storage: FileStoragePort,
        bucket: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._bucket = bucket

    async def submit(
        self,
        *,
        actor: ActorContext,
        kind: FeedbackKind,
        message: str,
        page_path: str,
        client: FeedbackClient,
        workspace_id: UUID | None,
        element: FeedbackElement | None,
        screenshot: tuple[str, bytes] | None,
    ) -> FeedbackReport:
        """Store one report; ``screenshot`` is ``(content_type, bytes)``."""

        if screenshot is not None:
            content_type, data = screenshot
            screenshot_format = _SCREENSHOT_FORMATS.get(content_type)
            if screenshot_format is None or not data.startswith(screenshot_format[0]):
                raise FeedbackScreenshotError(
                    f"Screenshot declared as {content_type!r} is not a PNG or JPEG"
                )
        now = datetime.now(UTC)
        report_id = uuid4()
        async with self._uow_factory() as uow:
            recent = await uow.feedback.count_by_reporter_since(
                actor.user_id, now - timedelta(hours=1)
            )
            if recent >= REPORTS_PER_HOUR:
                raise FeedbackRateLimitedError(
                    f"User {actor.user_id} sent {recent} reports in the last hour"
                )
            if workspace_id is not None:
                membership = await uow.identity.get_membership(
                    workspace_id=workspace_id, user_id=actor.user_id
                )
                # A Workspace the reporter cannot see is reported as missing.
                if membership is None or not membership.is_active:
                    raise NotFoundError("Workspace", str(workspace_id))
            stored = None
            if screenshot is not None:
                content_type, data = screenshot
                path = f"feedback/{report_id}.{_SCREENSHOT_FORMATS[content_type][1]}"
                await self._storage.save(
                    SaveFileCommand(
                        bucket=self._bucket,
                        path=path,
                        stream=io.BytesIO(data),
                        content_type=content_type,
                        metadata={"source": "feedback"},
                    )
                )
                stored = FeedbackScreenshot(
                    path=path, content_type=content_type, byte_size=len(data)
                )
            report = FeedbackReport(
                id=report_id,
                kind=kind,
                message=message,
                page_path=page_path,
                client=client,
                reporter_user_id=actor.user_id,
                workspace_id=workspace_id,
                element=element,
                screenshot=stored,
                created_at=now,
            )
            try:
                await uow.feedback.add(report)
                await uow.commit()
            except Exception:
                # The row never landed, so nothing will ever read or delete the object.
                if stored is not None:
                    await self._storage.delete(self._bucket, stored.path)
                raise
        return report

    async def list_reports(
        self,
        *,
        status: FeedbackStatus | None,
        before: datetime | None,
        limit: int,
    ) -> Sequence[FeedbackReportView]:
        async with self._uow_factory() as uow:
            reports = await uow.feedback.list_page(
                status=status, before=before, limit=limit
            )
            return [await self._view(uow, report) for report in reports]

    async def get_report(self, report_id: UUID) -> FeedbackReportView:
        async with self._uow_factory() as uow:
            report = await uow.feedback.get(report_id)
            if report is None:
                raise NotFoundError("Feedback report", str(report_id))
            return await self._view(uow, report)

    async def read_screenshot(self, report_id: UUID) -> tuple[str, bytes]:
        async with self._uow_factory() as uow:
            report = await uow.feedback.get(report_id)
        if report is None or report.screenshot is None:
            raise NotFoundError("Feedback screenshot", str(report_id))
        # The row can outlive its object, for example after the bucket changes.
        if await self._storage.stat(self._bucket, report.screenshot.path) is None:
            raise NotFoundError("Feedback screenshot", str(report_id))
        stream = await self._storage.load(self._bucket, report.screenshot.path)
        with stream:
            data = stream.read()
        return report.screenshot.content_type, data

    async def update_report(
        self,
        *,
        report_id: UUID,
        operator_user_id: UUID,
        status: FeedbackStatus | None,
        github_issue_url: str | None,
        replace_github_issue_url: bool,
    ) -> FeedbackReportView:
        """Resolve, reopen, or link a report to the GitHub issue filed for it.

        ``replace_github_issue_url`` says whether the caller sent the field at all,
        so an absent field leaves the link alone and an explicit ``None`` clears it.
        """

        async with self._uow_factory() as uow:
            report = await uow.feedback.get(report_id)
            if report is None:
                raise NotFoundError("Feedback report", str(report_id))
            if (
                status is FeedbackStatus.RESOLVED
                and report.status is FeedbackStatus.OPEN
            ):
                report.resolve(by_user_id=operator_user_id, at=datetime.now(UTC))
            if (
                status is FeedbackStatus.OPEN
                and report.status is FeedbackStatus.RESOLVED
            ):
                report.reopen()
            if replace_github_issue_url:
                report.github_issue_url = github_issue_url
            await uow.feedback.save(report)
            view = await self._view(uow, report)
            await uow.commit()
        return view

    async def delete_report(self, report_id: UUID) -> None:
        async with self._uow_factory() as uow:
            report = await uow.feedback.get(report_id)
            if report is None:
                raise NotFoundError("Feedback report", str(report_id))
            await uow.feedback.delete(report_id)
            await uow.commit()
        if report.screenshot is not None:
            await self._storage.delete(self._bucket, report.screenshot.path)

    async def _view(
        self, uow: FeedbackUnitOfWorkPort, report: FeedbackReport
    ) -> FeedbackReportView:
        reporter = None
        if report.reporter_user_id is not None:
            reporter = await uow.identity.get_user(report.reporter_user_id)
        workspace = None
        if report.workspace_id is not None:
            workspace = await uow.identity.get_workspace(report.workspace_id)
        return FeedbackReportView(report=report, reporter=reporter, workspace=workspace)


__all__ = [
    "MAX_SCREENSHOT_BYTES",
    "REPORTS_PER_HOUR",
    "FeedbackReportView",
    "FeedbackService",
]

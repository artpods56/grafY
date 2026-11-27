from collections.abc import Sequence
from datetime import datetime
from typing import Any, override
from uuid import UUID

from sqlalchemy import Row, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.feedback import (
    FeedbackReport,
    FeedbackScreenshot,
    FeedbackStatus,
)
from grafy_core.ports.feedback import FeedbackRepositoryPort
from grafy_persistence.schema import feedback_reports


def _report_from_row(row: Row[Any]) -> FeedbackReport:
    screenshot = None
    if row.screenshot_path is not None:
        screenshot = FeedbackScreenshot(
            path=row.screenshot_path,
            content_type=row.screenshot_content_type,
            byte_size=row.screenshot_byte_size,
        )
    return FeedbackReport(
        id=row.id,
        kind=row.kind,
        message=row.message,
        page_path=row.page_path,
        client=row.client,
        reporter_user_id=row.reporter_user_id,
        workspace_id=row.workspace_id,
        element=row.element,
        screenshot=screenshot,
        status=row.status,
        resolved_at=row.resolved_at,
        resolved_by_user_id=row.resolved_by_user_id,
        github_issue_url=row.github_issue_url,
        created_at=row.created_at,
    )


class SqlFeedbackRepository(FeedbackRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, report: FeedbackReport) -> None:
        screenshot = report.screenshot
        await self._session.execute(
            insert(feedback_reports).values(
                id=report.id,
                reporter_user_id=report.reporter_user_id,
                workspace_id=report.workspace_id,
                kind=report.kind,
                message=report.message,
                page_path=report.page_path,
                element=report.element,
                client=report.client,
                screenshot_path=None if screenshot is None else screenshot.path,
                screenshot_content_type=(
                    None if screenshot is None else screenshot.content_type
                ),
                screenshot_byte_size=(
                    None if screenshot is None else screenshot.byte_size
                ),
                status=report.status,
                resolved_at=report.resolved_at,
                resolved_by_user_id=report.resolved_by_user_id,
                github_issue_url=report.github_issue_url,
                created_at=report.created_at,
            )
        )

    @override
    async def get(self, report_id: UUID) -> FeedbackReport | None:
        result = await self._session.execute(
            select(feedback_reports).where(feedback_reports.c.id == report_id)
        )
        row = result.one_or_none()
        return None if row is None else _report_from_row(row)

    @override
    async def save(self, report: FeedbackReport) -> None:
        await self._session.execute(
            update(feedback_reports)
            .where(feedback_reports.c.id == report.id)
            .values(
                status=report.status,
                resolved_at=report.resolved_at,
                resolved_by_user_id=report.resolved_by_user_id,
                github_issue_url=report.github_issue_url,
            )
        )

    @override
    async def delete(self, report_id: UUID) -> None:
        await self._session.execute(
            delete(feedback_reports).where(feedback_reports.c.id == report_id)
        )

    @override
    async def list_page(
        self,
        *,
        status: FeedbackStatus | None,
        before: datetime | None,
        limit: int,
    ) -> Sequence[FeedbackReport]:
        query = (
            select(feedback_reports)
            .order_by(
                feedback_reports.c.created_at.desc(), feedback_reports.c.id.desc()
            )
            .limit(limit)
        )
        if status is not None:
            query = query.where(feedback_reports.c.status == status)
        if before is not None:
            query = query.where(feedback_reports.c.created_at < before)
        result = await self._session.execute(query)
        return [_report_from_row(row) for row in result]

    @override
    async def count_by_reporter_since(
        self, reporter_user_id: UUID, since: datetime
    ) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(feedback_reports)
            .where(
                feedback_reports.c.reporter_user_id == reporter_user_id,
                feedback_reports.c.created_at >= since,
            )
        )
        return count or 0

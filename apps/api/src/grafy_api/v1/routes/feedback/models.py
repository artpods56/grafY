from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from grafy_api.feedback import FeedbackReportView
from grafy_core.domain.feedback import (
    FeedbackClient,
    FeedbackElement,
    FeedbackKind,
    FeedbackStatus,
)


class FeedbackReportSubmission(BaseModel):
    """The JSON a browser sends in the ``report`` form field."""

    model_config = ConfigDict(extra="forbid")

    kind: FeedbackKind
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    page_path: str = Field(min_length=1, max_length=2048, pattern=r"^/")
    workspace_id: UUID | None = None
    element: FeedbackElement | None = None
    client: FeedbackClient


class FeedbackReceiptResponse(BaseModel):
    id: UUID
    created_at: datetime


class FeedbackReporterResponse(BaseModel):
    id: UUID
    email: str | None
    display_name: str | None


class FeedbackWorkspaceResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class FeedbackScreenshotResponse(BaseModel):
    content_type: str
    byte_size: int


class FeedbackReportResponse(BaseModel):
    id: UUID
    created_at: datetime
    kind: FeedbackKind
    message: str
    page_path: str
    status: FeedbackStatus
    resolved_at: datetime | None
    github_issue_url: str | None
    reporter: FeedbackReporterResponse | None
    workspace: FeedbackWorkspaceResponse | None
    element: FeedbackElement | None
    client: FeedbackClient
    screenshot: FeedbackScreenshotResponse | None

    @classmethod
    def from_view(cls, view: FeedbackReportView) -> "FeedbackReportResponse":
        report = view.report
        reporter = None
        if view.reporter is not None:
            reporter = FeedbackReporterResponse(
                id=view.reporter.id,
                email=view.reporter.email,
                display_name=view.reporter.display_name,
            )
        workspace = None
        if view.workspace is not None:
            workspace = FeedbackWorkspaceResponse(
                id=view.workspace.id,
                slug=view.workspace.slug,
                name=view.workspace.name,
            )
        screenshot = None
        if report.screenshot is not None:
            screenshot = FeedbackScreenshotResponse(
                content_type=report.screenshot.content_type,
                byte_size=report.screenshot.byte_size,
            )
        return cls(
            id=report.id,
            created_at=report.created_at,
            kind=report.kind,
            message=report.message,
            page_path=report.page_path,
            status=report.status,
            resolved_at=report.resolved_at,
            github_issue_url=report.github_issue_url,
            reporter=reporter,
            workspace=workspace,
            element=report.element,
            client=report.client,
            screenshot=screenshot,
        )


class FeedbackReportListResponse(BaseModel):
    items: list[FeedbackReportResponse]
    next_before: datetime | None


class FeedbackReportUpdate(BaseModel):
    """Fields left out stay as they are; ``github_issue_url: null`` clears the link."""

    model_config = ConfigDict(extra="forbid")

    status: FeedbackStatus | None = None
    github_issue_url: str | None = Field(
        default=None, max_length=500, pattern=r"^https://github\.com/\S+$"
    )

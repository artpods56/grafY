"""Feedback reports: anyone signed in sends one; operators triage them.

Every route takes a browser session only. A PAT is bound to one Workspace, and
a report is about the app rather than a Workspace, so automation has no say here.
"""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import AwareDatetime, ValidationError

from grafy_core.domain.feedback import FeedbackStatus
from grafy_core.domain.identity import ActorContext

from grafy_api.feedback import MAX_SCREENSHOT_BYTES
from grafy_api.v1.routes.auth.dependencies import browser_actor, operator_actor

from .dependencies import FeedbackDependency
from .models import (
    FeedbackReceiptResponse,
    FeedbackReportListResponse,
    FeedbackReportResponse,
    FeedbackReportSubmission,
    FeedbackReportUpdate,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])
admin_router = APIRouter(
    prefix="/admin/feedback",
    tags=["admin"],
    dependencies=[Depends(operator_actor)],
)


@router.post(
    "",
    response_model=FeedbackReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    actor: Annotated[ActorContext, Depends(browser_actor)],
    service: FeedbackDependency,
    report: Annotated[str, Form(description="FeedbackReportSubmission as JSON")],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> FeedbackReceiptResponse:
    try:
        submission = FeedbackReportSubmission.model_validate_json(report)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(
                include_url=False, include_context=False, include_input=False
            ),
        ) from exc
    attached = None
    if screenshot is not None:
        data = await screenshot.read(MAX_SCREENSHOT_BYTES + 1)
        if len(data) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(status_code=413, detail="Screenshot exceeds 2 MiB")
        attached = (screenshot.content_type or "", data)
    created = await service.submit(
        actor=actor,
        kind=submission.kind,
        message=submission.message,
        page_path=submission.page_path,
        client=submission.client,
        workspace_id=submission.workspace_id,
        element=submission.element,
        screenshot=attached,
    )
    return FeedbackReceiptResponse(id=created.id, created_at=created.created_at)


@admin_router.get("", response_model=FeedbackReportListResponse)
async def list_feedback_reports(
    service: FeedbackDependency,
    status_filter: Annotated[FeedbackStatus | None, Query(alias="status")] = None,
    before: Annotated[AwareDatetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FeedbackReportListResponse:
    views = await service.list_reports(status=status_filter, before=before, limit=limit)
    items = [FeedbackReportResponse.from_view(view) for view in views]
    next_before = items[-1].created_at if len(items) == limit else None
    return FeedbackReportListResponse(items=items, next_before=next_before)


@admin_router.get("/{report_id}", response_model=FeedbackReportResponse)
async def get_feedback_report(
    report_id: UUID, service: FeedbackDependency
) -> FeedbackReportResponse:
    return FeedbackReportResponse.from_view(await service.get_report(report_id))


@admin_router.get(
    "/{report_id}/screenshot",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
async def get_feedback_screenshot(
    report_id: UUID, service: FeedbackDependency
) -> Response:
    content_type, data = await service.read_screenshot(report_id)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@admin_router.patch("/{report_id}", response_model=FeedbackReportResponse)
async def update_feedback_report(
    report_id: UUID,
    update: FeedbackReportUpdate,
    actor: Annotated[ActorContext, Depends(operator_actor)],
    service: FeedbackDependency,
) -> FeedbackReportResponse:
    view = await service.update_report(
        report_id=report_id,
        operator_user_id=actor.user_id,
        status=update.status,
        github_issue_url=update.github_issue_url,
        replace_github_issue_url="github_issue_url" in update.model_fields_set,
    )
    return FeedbackReportResponse.from_view(view)


@admin_router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback_report(
    report_id: UUID, service: FeedbackDependency
) -> Response:
    await service.delete_report(report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

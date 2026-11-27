"""Feedback reports: what a signed-in person says about the app, and where on screen."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from grafy_core.domain.errors import FailureKind, FailureSpec, GrafyCoreError


class FeedbackKind(StrEnum):
    BUG = "bug"
    IDEA = "idea"
    OTHER = "other"


class FeedbackStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class FeedbackRect(BaseModel):
    """The picked element's box in CSS pixels, relative to the viewport."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class FeedbackElement(BaseModel):
    """The element a person picked, described well enough to find it again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str = Field(min_length=1, max_length=32)
    selector: str = Field(min_length=1, max_length=1000)
    label: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=64)
    test_id: str | None = Field(default=None, max_length=200)
    canvas_item_id: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=500)
    rect: FeedbackRect


class FeedbackClient(BaseModel):
    """The browser the report came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    viewport_width: int = Field(ge=1, le=100_000)
    viewport_height: int = Field(ge=1, le=100_000)
    device_pixel_ratio: float = Field(gt=0, le=16)
    user_agent: str = Field(max_length=512)
    color_scheme: Literal["light", "dark"]


@dataclass(frozen=True, slots=True)
class FeedbackScreenshot:
    path: str
    content_type: str
    byte_size: int


@dataclass
class FeedbackReport:
    """One report about the app. Operators triage it; no Workspace owns it.

    ``workspace_id`` only records which Workspace the page belonged to. It was
    checked against the reporter's membership when the report arrived.
    """

    kind: FeedbackKind
    message: str
    page_path: str
    client: FeedbackClient
    reporter_user_id: UUID | None
    workspace_id: UUID | None = None
    element: FeedbackElement | None = None
    screenshot: FeedbackScreenshot | None = None
    status: FeedbackStatus = FeedbackStatus.OPEN
    resolved_at: datetime | None = None
    resolved_by_user_id: UUID | None = None
    github_issue_url: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def resolve(self, *, by_user_id: UUID, at: datetime) -> None:
        self.status = FeedbackStatus.RESOLVED
        self.resolved_at = at
        self.resolved_by_user_id = by_user_id

    def reopen(self) -> None:
        self.status = FeedbackStatus.OPEN
        self.resolved_at = None
        self.resolved_by_user_id = None


class FeedbackRateLimitedError(GrafyCoreError):
    """Raised when one person sends more reports in an hour than the limit allows."""

    failure_spec = FailureSpec(
        code="feedback.rate_limited",
        kind=FailureKind.CAPACITY,
        public_message="Too many feedback reports; try again later",
    )


class FeedbackScreenshotError(GrafyCoreError):
    """Raised when an attached screenshot is not a PNG or JPEG its bytes agree with."""

    failure_spec = FailureSpec(
        code="feedback.screenshot_invalid",
        kind=FailureKind.VALIDATION,
        public_message="Screenshot must be a PNG or JPEG image",
    )

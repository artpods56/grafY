from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.feedback import FeedbackService


def feedback_service(request: Request) -> FeedbackService:
    return get_resources(request.app).feedback


FeedbackDependency = Annotated[FeedbackService, Depends(feedback_service)]

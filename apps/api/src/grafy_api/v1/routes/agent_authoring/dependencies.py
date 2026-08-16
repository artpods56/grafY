from typing import Annotated

from fastapi import Depends, Request

from grafy_core.application.agent_authoring import AgentAuthoringService

from grafy_api.app_state import get_resources

from .services import BuildReviewService


def agent_authoring_service(request: Request) -> AgentAuthoringService:
    return get_resources(request.app).agent_authoring


AgentAuthoringDependency = Annotated[
    AgentAuthoringService,
    Depends(agent_authoring_service),
]


def build_review_service(request: Request) -> BuildReviewService:
    return get_resources(request.app).build_review


BuildReviewDependency = Annotated[
    BuildReviewService,
    Depends(build_review_service),
]


__all__ = [
    "AgentAuthoringDependency",
    "BuildReviewDependency",
    "agent_authoring_service",
    "build_review_service",
]

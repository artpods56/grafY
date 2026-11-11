"""Operator-only user administration.

These routes are platform-wide, not Workspace-scoped: disabling a user signs them
out of every Workspace. They accept browser sessions only, because a PAT is bound
to one Workspace and never carries operator authority, and the service refuses
anyone whose verified email is not in `GRAFY_OPERATOR_EMAILS`.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from grafy_core.domain.identity import ActorContext

from grafy_api.v1.routes.admin.models import AdminUserResponse
from grafy_api.v1.routes.auth.dependencies import (
    IdentityServiceDependency,
    browser_actor,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: UUID,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    identity: IdentityServiceDependency,
) -> AdminUserResponse:
    user = await identity.get_user_for_operator(actor=actor, user_id=user_id)
    return AdminUserResponse.from_user(user)


@router.post("/users/{user_id}/disable", response_model=AdminUserResponse)
async def disable_user(
    user_id: UUID,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    identity: IdentityServiceDependency,
) -> AdminUserResponse:
    user = await identity.disable_user(actor=actor, user_id=user_id)
    return AdminUserResponse.from_user(user)


@router.post("/users/{user_id}/enable", response_model=AdminUserResponse)
async def enable_user(
    user_id: UUID,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    identity: IdentityServiceDependency,
) -> AdminUserResponse:
    user = await identity.enable_user(actor=actor, user_id=user_id)
    return AdminUserResponse.from_user(user)

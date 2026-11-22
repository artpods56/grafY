import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
)

from grafy_api.app_state import get_resources
from grafy_api.realtime.publish import rederive_instances
from grafy_api.v1.routes.auth.dependencies import (
    browser_actor,
    require_workspace_capability_dependency,
)
from grafy_api.v1.routes.credentials.dependencies import CredentialDependency
from grafy_api.v1.routes.credentials.models import (
    CreateCredentialRequest,
    CredentialListResponse,
    CredentialResponse,
    CredentialVerificationFailureResponse,
    CredentialVerificationResponse,
    UpdateCredentialRequest,
    VerifyCandidateCredentialRequest,
    VerifySavedCredentialRequest,
    verification_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["credentials"])
_PERSONAL = "/me/credentials"
_SHARED = "/workspaces/{workspace_id}/credentials"
_VERIFICATION_FAILURE: dict[int | str, dict[str, object]] = {
    422: {"model": CredentialVerificationFailureResponse}
}


async def _publish_shared_change(request: Request, workspace_id: UUID) -> None:
    resources = get_resources(request.app)
    try:
        projects = await resources.projects.list(workspace_id=workspace_id)
    except Exception:
        logger.exception(
            "credential_project_listing_failed workspace_id=%s", workspace_id
        )
        return
    for project in projects:
        await rederive_instances(
            resources.runs, workspace_id=workspace_id, project_id=project.id
        )


@router.get(_PERSONAL)
async def list_personal_credentials(
    service: CredentialDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    provider_kind: str | None = None,
) -> CredentialListResponse:
    rows = await service.list_personal(actor.user_id, provider_kind)
    return CredentialListResponse(
        credentials=[CredentialResponse.model_validate(row) for row in rows]
    )


@router.post(_PERSONAL, status_code=201, responses=_VERIFICATION_FAILURE)
async def create_personal_credential(
    body: CreateCredentialRequest,
    service: CredentialDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
) -> CredentialResponse:
    if body.verify:
        service.check_verify_rate(actor.user_id)
    row = await service.create_personal(
        user_id=actor.user_id,
        provider_kind=body.provider_kind,
        label=body.label,
        value=body.value,
        verify=body.verify,
        save_if_unverified=body.save_if_unverified,
        verify_config=verification_config(body.verify_config),
    )
    return CredentialResponse.model_validate(row)


@router.post(_PERSONAL + "/verify")
async def verify_personal_candidate(
    body: VerifyCandidateCredentialRequest,
    service: CredentialDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
) -> CredentialVerificationResponse:
    service.check_verify_rate(actor.user_id)
    result = await service.verify_candidate(
        provider_kind=body.provider_kind,
        value=body.value,
        config=verification_config(body.config),
    )
    return CredentialVerificationResponse.model_validate(result)


@router.post(_PERSONAL + "/{credential_id}/verify")
async def verify_saved_personal_credential(
    credential_id: UUID,
    service: CredentialDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    body: VerifySavedCredentialRequest | None = None,
) -> CredentialResponse:
    service.check_verify_rate(actor.user_id)
    row = await service.verify_saved_personal(
        user_id=actor.user_id,
        credential_id=credential_id,
        config=verification_config(body.config) if body else None,
    )
    return CredentialResponse.model_validate(row)


@router.patch(_PERSONAL + "/{credential_id}", responses=_VERIFICATION_FAILURE)
async def update_personal_credential(
    credential_id: UUID,
    body: UpdateCredentialRequest,
    service: CredentialDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
) -> CredentialResponse:
    if body.verify and body.value is not None:
        service.check_verify_rate(actor.user_id)
    row = await service.update_personal(
        user_id=actor.user_id,
        credential_id=credential_id,
        label=body.label,
        value=body.value,
        verify=body.verify,
        save_if_unverified=body.save_if_unverified,
        verify_config=verification_config(body.verify_config)
        if body.verify_config is not None
        else None,
    )
    return CredentialResponse.model_validate(row)


@router.delete(_PERSONAL + "/{credential_id}", status_code=204)
async def delete_personal_credential(
    credential_id: UUID,
    service: CredentialDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
) -> Response:
    await service.delete_personal(actor.user_id, credential_id)
    return Response(status_code=204)


@router.get(_SHARED)
async def list_shared_credentials(
    service: CredentialDependency,
    access: Annotated[
        WorkspaceAccess,
        require_workspace_capability_dependency(WorkspaceCapability.VIEW_PROJECT),
    ],
    provider_kind: str | None = None,
) -> CredentialListResponse:
    rows = await service.list_shared(access.workspace_id, provider_kind)
    return CredentialListResponse(
        credentials=[CredentialResponse.model_validate(row) for row in rows]
    )


@router.post(_SHARED, status_code=201, responses=_VERIFICATION_FAILURE)
async def create_shared_credential(
    body: CreateCredentialRequest,
    service: CredentialDependency,
    access: Annotated[
        WorkspaceAccess,
        require_workspace_capability_dependency(WorkspaceCapability.MANAGE_SECRETS),
    ],
) -> CredentialResponse:
    if body.verify:
        service.check_verify_rate(access.actor.user_id)
    row = await service.create_shared(
        workspace_id=access.workspace_id,
        created_by_user_id=access.actor.user_id,
        provider_kind=body.provider_kind,
        label=body.label,
        value=body.value,
        verify=body.verify,
        save_if_unverified=body.save_if_unverified,
        verify_config=verification_config(body.verify_config),
    )
    return CredentialResponse.model_validate(row)


@router.post(_SHARED + "/verify")
async def verify_shared_candidate(
    body: VerifyCandidateCredentialRequest,
    service: CredentialDependency,
    access: Annotated[
        WorkspaceAccess,
        require_workspace_capability_dependency(WorkspaceCapability.MANAGE_SECRETS),
    ],
) -> CredentialVerificationResponse:
    service.check_verify_rate(access.actor.user_id)
    result = await service.verify_candidate(
        provider_kind=body.provider_kind,
        value=body.value,
        config=verification_config(body.config),
    )
    return CredentialVerificationResponse.model_validate(result)


@router.post(_SHARED + "/{credential_id}/verify")
async def verify_saved_shared_credential(
    credential_id: UUID,
    service: CredentialDependency,
    access: Annotated[
        WorkspaceAccess,
        require_workspace_capability_dependency(WorkspaceCapability.MANAGE_SECRETS),
    ],
    body: VerifySavedCredentialRequest | None = None,
) -> CredentialResponse:
    service.check_verify_rate(access.actor.user_id)
    row = await service.verify_saved_shared(
        workspace_id=access.workspace_id,
        credential_id=credential_id,
        config=verification_config(body.config) if body else None,
    )
    return CredentialResponse.model_validate(row)


@router.patch(_SHARED + "/{credential_id}", responses=_VERIFICATION_FAILURE)
async def update_shared_credential(
    request: Request,
    credential_id: UUID,
    body: UpdateCredentialRequest,
    service: CredentialDependency,
    access: Annotated[
        WorkspaceAccess,
        require_workspace_capability_dependency(WorkspaceCapability.MANAGE_SECRETS),
    ],
) -> CredentialResponse:
    if body.verify and body.value is not None:
        service.check_verify_rate(access.actor.user_id)
    row = await service.update_shared(
        workspace_id=access.workspace_id,
        credential_id=credential_id,
        label=body.label,
        value=body.value,
        verify=body.verify,
        save_if_unverified=body.save_if_unverified,
        verify_config=verification_config(body.verify_config)
        if body.verify_config is not None
        else None,
    )
    if body.value is not None:
        await _publish_shared_change(request, access.workspace_id)
    return CredentialResponse.model_validate(row)


@router.delete(_SHARED + "/{credential_id}", status_code=204)
async def delete_shared_credential(
    request: Request,
    credential_id: UUID,
    service: CredentialDependency,
    access: Annotated[
        WorkspaceAccess,
        require_workspace_capability_dependency(WorkspaceCapability.MANAGE_SECRETS),
    ],
) -> Response:
    await service.delete_shared(access.workspace_id, credential_id)
    await _publish_shared_change(request, access.workspace_id)
    return Response(status_code=204)

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException

from grafy_core.application.identity import authorize_workspace
from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability

from grafy_api.catalog import CatalogSnapshot
from grafy_api.v1.routes.auth.dependencies import (
    IdentityUnitOfWorkFactoryDependency,
    require_workspace_capability_dependency,
)

from .dependencies import CatalogPolicyDependency, PluginRegistryDependency
from .models import (
    CatalogPackResponse,
    NodeRegistryResponse,
    SetPackSubscriptionRequest,
)


ViewCatalogAccess = Annotated[
    WorkspaceAccess,
    require_workspace_capability_dependency(WorkspaceCapability.VIEW_PROJECT),
]
ManagePacksAccess = Annotated[
    WorkspaceAccess,
    require_workspace_capability_dependency(WorkspaceCapability.MANAGE_PACKS),
]

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


@router.get("/nodes", response_model=NodeRegistryResponse)
async def list_nodes(
    registry: PluginRegistryDependency,
    access: ViewCatalogAccess,
    policy: CatalogPolicyDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
) -> NodeRegistryResponse:
    async with uow_factory() as uow:
        subscribed = await uow.workspace_packs.list_slugs(access.workspace_id)
    return NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(registry),
        policy,
        subscribed | policy.always_on_slugs,
    )


@router.get("/packs", response_model=list[CatalogPackResponse])
async def list_packs(
    access: ViewCatalogAccess,
    policy: CatalogPolicyDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
) -> list[CatalogPackResponse]:
    async with uow_factory() as uow:
        subscribed = await uow.workspace_packs.list_slugs(access.workspace_id)
    subscribed |= policy.always_on_slugs
    return [
        CatalogPackResponse.from_pack(pack, pack.definition.slug in subscribed)
        for pack in policy.packs
    ]


@router.put("/packs/{pack_slug}", response_model=CatalogPackResponse)
async def set_pack_subscription(
    pack_slug: str,
    body: SetPackSubscriptionRequest,
    access: ManagePacksAccess,
    policy: CatalogPolicyDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
) -> CatalogPackResponse:
    pack = next(
        (pack for pack in policy.packs if pack.definition.slug == pack_slug), None
    )
    if pack is None:
        raise HTTPException(status_code=404, detail="Pack not found")
    if not body.subscribed and pack.definition.always_on:
        raise HTTPException(status_code=400, detail="This pack is always on")

    async with uow_factory() as uow:
        await authorize_workspace(
            uow.identity,
            actor=access.actor,
            workspace_id=access.workspace_id,
            capability=WorkspaceCapability.MANAGE_PACKS,
        )
        if body.subscribed:
            await uow.workspace_packs.enable(
                access.workspace_id,
                pack_slug,
                enabled_at=datetime.now(UTC),
                enabled_by_user_id=access.actor.user_id,
            )
        else:
            await uow.workspace_packs.disable(access.workspace_id, pack_slug)
        await uow.commit()
    return CatalogPackResponse.from_pack(pack, body.subscribed)


__all__ = ["router"]

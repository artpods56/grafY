"""The starter service, built from the resources a request already has."""

from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_identity, get_resources
from grafy_api.starters import StarterService


def starter_service(request: Request) -> StarterService:
    resources = get_resources(request.app)
    identity = get_identity(request.app)
    return StarterService(
        uploads=resources.workbench.uploads,
        library=resources.workbench.library,
        collaboration=resources.collaboration,
        credentials=resources.credentials,
        node_secrets=resources.node_secrets,
        registry=resources.workbench.plugin_registry,
        policy=identity.catalog_policy,
        identity_uow_factory=identity.identity_uow_factory,
    )


StarterDependency = Annotated[StarterService, Depends(starter_service)]

__all__ = ["StarterDependency", "starter_service"]

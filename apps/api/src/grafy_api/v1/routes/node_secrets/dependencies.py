from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.node_secrets import NodeSecretService


def node_secret_service(request: Request) -> NodeSecretService:
    return get_resources(request.app).node_secrets


NodeSecretDependency = Annotated[NodeSecretService, Depends(node_secret_service)]


__all__ = ["NodeSecretDependency", "node_secret_service"]

from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.node_secrets import NodeSecretService
from grafy_api.runs.service import RunService


def node_secret_service(request: Request) -> NodeSecretService:
    return get_resources(request.app).node_secrets


def run_service(request: Request) -> RunService:
    return get_resources(request.app).runs


NodeSecretDependency = Annotated[NodeSecretService, Depends(node_secret_service)]

RunDependency = Annotated[RunService, Depends(run_service)]


__all__ = [
    "NodeSecretDependency",
    "RunDependency",
    "node_secret_service",
    "run_service",
]

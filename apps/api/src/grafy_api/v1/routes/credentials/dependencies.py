from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.credentials import CredentialService


def credential_service(request: Request) -> CredentialService:
    return get_resources(request.app).credentials


CredentialDependency = Annotated[CredentialService, Depends(credential_service)]

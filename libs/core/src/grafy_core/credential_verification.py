from collections.abc import Callable, Mapping

import httpx
from pydantic import AnyHttpUrl, SecretStr, TypeAdapter

from grafy_core.domain.credentials import (
    CredentialVerificationResult,
)
from grafy_core.domain.credentials import (
    CredentialVerificationStatus as Status,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.egress import EgressRejectedError
from grafy_core.plugins import CredentialVerifier

UNREACHABLE = CredentialVerificationResult(
    Status.UNREACHABLE, "Could not reach provider endpoint to verify key."
)
EGRESS_BLOCKED = CredentialVerificationResult(
    Status.EGRESS_BLOCKED, "Endpoint is blocked by deployment egress policy."
)


def verification_endpoint(value: JsonValue) -> str:
    url = TypeAdapter(AnyHttpUrl).validate_python(value)
    if any(
        part is not None
        for part in (url.username, url.password, url.query, url.fragment)
    ):
        raise ValueError("Endpoint URLs must omit credentials, queries and fragments")
    return str(url).rstrip("/")


async def verify_http_credential(
    client: httpx.AsyncClient,
    url: str,
    authorization: str,
    *,
    message: str,
    account_hint: Callable[[object], str | None] | None = None,
    missing_endpoint_message: str | None = None,
) -> CredentialVerificationResult:
    try:
        async with client.stream(
            "GET", url, headers={"Authorization": authorization}, follow_redirects=False
        ) as response:
            if response.status_code in {401, 403}:
                return CredentialVerificationResult(
                    Status.INVALID, "Provider rejected the API key."
                )
            if response.status_code == 404 and missing_endpoint_message:
                return CredentialVerificationResult(
                    Status.UNREACHABLE, missing_endpoint_message
                )
            if response.status_code != 200:
                return UNREACHABLE
            hint = None
            if account_hint is not None:
                # Providers can return large bodies. A hint is optional.
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 262_144:
                        break
                else:
                    import json

                    try:
                        hint = account_hint(json.loads(body))
                    except (ValueError, RecursionError):
                        pass
            return CredentialVerificationResult(Status.VALID, message, hint)
    except EgressRejectedError:
        return EGRESS_BLOCKED
    except httpx.HTTPError:
        return UNREACHABLE


def unsupported_credential_verifier(message: str) -> CredentialVerifier:
    async def verify(
        value: SecretStr, config: Mapping[str, JsonValue], client: httpx.AsyncClient
    ) -> CredentialVerificationResult:
        return CredentialVerificationResult(Status.UNSUPPORTED, message)

    return verify

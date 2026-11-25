from collections.abc import Mapping

import httpx
from grafy_core.credential_verification import UNREACHABLE
from grafy_core.domain.credentials import CredentialVerificationResult
from grafy_core.domain.credentials import CredentialVerificationStatus as Status
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.plugins import NodeSecretInput
from pydantic import SecretStr

LITELLM_ORIGIN = "https://ai-test.ihpan.edu.pl"


async def _verify_api_key(
    key: SecretStr, _config: Mapping[str, JsonValue], client: httpx.AsyncClient
) -> CredentialVerificationResult:
    paths = ("/key/info", "/v1/models")
    headers = {"Authorization": f"Bearer {key.get_secret_value()}"}
    unauthorized = 0
    for path in paths:
        async with client.stream(
            "GET", f"{LITELLM_ORIGIN}{path}", headers=headers, follow_redirects=False
        ) as response:
            status = response.status_code
        if status == 200:
            return CredentialVerificationResult(
                Status.VALID,
                "LiteLLM accepted the API key. OCR route access is checked during a run.",
            )
        if status == 401:
            unauthorized += 1
        elif status not in {400, 403, 404}:
            return UNREACHABLE

    if unauthorized == len(paths):
        return CredentialVerificationResult(
            Status.INVALID,
            "LiteLLM rejected the API key on both verification endpoints.",
        )
    return CredentialVerificationResult(
        Status.UNSUPPORTED,
        "The LiteLLM verification endpoints could not confirm this key. "
        "OCR route access can be checked during a run.",
    )


API_KEY = NodeSecretInput(
    name="api_key",
    title="LiteLLM API key",
    provider_kind="litellm",
    verifier=_verify_api_key,
)

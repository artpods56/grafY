from grafy_core.credential_verification import unsupported_credential_verifier
from grafy_core.plugins import NodeSecretInput

API_KEY = NodeSecretInput(
    name="api_key",
    title="LiteLLM API key",
    provider_kind="litellm",
    verifier=unsupported_credential_verifier("This key will be checked on first run."),
)

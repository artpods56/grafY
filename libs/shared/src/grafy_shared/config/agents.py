"""The deployment's default Agent model: endpoint, model name, and its key.

An Agent uses this unless whoever configures it gives it an endpoint and key of its own
(ADR 0021). One triple describes one OpenAI-compatible chat endpoint, the same shape the
LLM family dials.

The endpoint may name a destination a node could never reach — a model server on the
local network is exactly why ``EgressConfig.egress_trusted_destinations`` exists — so
nothing here rejects a private address. The decision stays with `grafy_core.egress` at
dial time, which is where an operator grant is consulted and a name's answers are checked
one by one. What this section does settle, at startup, is that the value is a nameable
query-free service endpoint: a malformed default should fail the process that was
configured wrong rather than the first person who sends a message.
"""

from typing import ClassVar

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class AgentsConfig(BaseSettings):
    """Operator-declared default model for Agents. The key is secret and has no dump path."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    agent_default_base_url: AnyHttpUrl | None = None
    agent_default_model: str | None = Field(default=None, max_length=255)
    agent_default_api_key: SecretStr | None = None

    @field_validator("agent_default_base_url")
    @classmethod
    def validate_base_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return value
        if value.username is not None or value.password is not None:
            raise ValueError(
                "GRAFY_AGENT_DEFAULT_BASE_URL must not carry embedded credentials"
            )
        if value.query:
            raise ValueError(
                "GRAFY_AGENT_DEFAULT_BASE_URL must be a query-free service endpoint"
            )
        if value.scheme not in ("http", "https"):
            raise ValueError(
                "GRAFY_AGENT_DEFAULT_BASE_URL must be an http or https endpoint"
            )
        return value

    @property
    def is_configured(self) -> bool:
        """Whether all three parts of a default are present.

        Half a default is not a default: a model name with no endpoint would dial
        api.openai.com by SDK accident, and an endpoint with no key would send an
        anonymous request. The resolver says which part is missing.
        """

        return self.incomplete_default() is None

    def incomplete_default(self) -> str | None:
        """The name of the first missing part of the default, or ``None``."""

        for name, value in (
            ("GRAFY_AGENT_DEFAULT_MODEL", self.agent_default_model),
            ("GRAFY_AGENT_DEFAULT_BASE_URL", self.agent_default_base_url),
            ("GRAFY_AGENT_DEFAULT_API_KEY", self.agent_default_api_key),
        ):
            if value is None or (isinstance(value, str) and not value.strip()):
                return name
            if isinstance(value, SecretStr) and not value.get_secret_value().strip():
                return name
        return None


__all__ = ["AgentsConfig"]

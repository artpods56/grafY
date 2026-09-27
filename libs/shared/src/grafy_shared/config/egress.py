"""Network egress authority granted to Plugin execution."""

from pathlib import Path
from typing import ClassVar

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class EgressConfig(BaseSettings):
    """Where Plugin code is allowed to reach, and through which broker."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    # Legacy translation inputs. When GRAFY_NETWORK_POLICY_MANIFEST is set it
    # owns plugin-execution HTTP authority and these values are ignored for
    # that plane (they remain the source for postgresql.egress only).
    plugin_http_egress_destinations: tuple[str, ...] = ()
    plugin_postgresql_egress_destinations: tuple[str, ...] = ()
    # Versioned deployment manifest of network access profiles and their
    # assignments. When configured, it replaces legacy HTTP destination grants
    # for Plugin execution; its absence translates the legacy egress variables.
    network_policy_manifest: Path | None = None
    plugin_egress_broker_image: str | None = None

    @field_validator("plugin_egress_broker_image", mode="before")
    @classmethod
    def empty_plugin_egress_broker_image_is_unset(
        cls,
        value: object,
    ) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_broker_and_destinations_together(self) -> "EgressConfig":
        # A broker image without an allowlist, or an allowlist without a broker,
        # is a half-wired deployment. Destination syntax itself is validated by
        # PluginEgressBrokerPolicy.from_config, which owns the destination
        # grammar and is built by the composition root.
        destinations = (
            *self.plugin_http_egress_destinations,
            *self.plugin_postgresql_egress_destinations,
        )
        if self.network_policy_manifest is None and (
            bool(self.plugin_egress_broker_image) != bool(destinations)
        ):
            raise ValueError(
                "plugin_egress_broker_image and at least one exact egress "
                "destination must be configured together"
            )
        return self

    @property
    def resolved_network_policy_manifest(self) -> Path | None:
        if self.network_policy_manifest is None:
            return None
        return self.network_policy_manifest.expanduser().resolve()

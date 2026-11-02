"""Egress authority: which private destinations this deployment may dial."""

from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class EgressConfig(BaseSettings):
    """Exact destinations an operator declares reachable even though they are not
    public addresses (ADR 0017): a self-hosted database behind a private address, or
    a model server on the local network.

    `grafy_core.egress` owns the grammar and the decision; this field exists so the
    variable belongs to the declared configuration surface and a malformed value is
    operator-visible at startup. A node, a graph and a Workspace can never widen the
    grant, and no destination can be requested through an HTTP header or a body.
    """

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    egress_trusted_destinations: tuple[str, ...] = ()


__all__ = ["EgressConfig"]

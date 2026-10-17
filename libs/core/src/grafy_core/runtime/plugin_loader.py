"""Immutable image-owned Plugin guest loader contract."""

from hashlib import sha256
import re
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


PLUGIN_GUEST_LOADER_MANIFEST = "grafy-plugin-guest-loader@2"
DEFAULT_PLUGIN_LOADER_TARGET = "grafy_plugin:PLUGIN"
PLUGIN_LOADER_TARGET_PATTERN = (
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r":[A-Za-z_][A-Za-z0-9_]*$"
)


def split_plugin_loader_target(value: str) -> tuple[str, str]:
    """Validate and split one explicit module-and-attribute import target."""

    if (
        value != value.strip()
        or len(value) > 512
        or re.fullmatch(PLUGIN_LOADER_TARGET_PATTERN, value) is None
    ):
        raise ValueError("Plugin loader target is not a valid module:attribute")
    module_name, attribute_name = value.split(":", maxsplit=1)
    return module_name, attribute_name


class PluginGuestLoaderManifest(BaseModel):
    """Exact import target baked into one retained Plugin runtime image."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    manifest_version: Literal["grafy-plugin-guest-loader@2"] = (
        PLUGIN_GUEST_LOADER_MANIFEST
    )
    slug: str = Field(
        pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$",
        max_length=100,
    )
    loader_target: str = Field(
        pattern=PLUGIN_LOADER_TARGET_PATTERN,
        max_length=512,
    )

    @field_validator("loader_target")
    @classmethod
    def validate_loader_target(cls, value: str) -> str:
        split_plugin_loader_target(value)
        return value

    @classmethod
    def from_json_bytes(cls, value: bytes) -> Self:
        return cls.model_validate_json(value)

    def canonical_json_bytes(self) -> bytes:
        return (self.model_dump_json() + "\n").encode("utf-8")

    @property
    def digest(self) -> str:
        return sha256(self.canonical_json_bytes()).hexdigest()


__all__ = [
    "PLUGIN_GUEST_LOADER_MANIFEST",
    "PLUGIN_LOADER_TARGET_PATTERN",
    "PluginGuestLoaderManifest",
    "DEFAULT_PLUGIN_LOADER_TARGET",
    "split_plugin_loader_target",
]

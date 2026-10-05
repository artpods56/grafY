"""Exact runtime identity of one executable node implementation."""

from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.saved_graphs import SavedGraphPluginReleasePin


_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class ImplementationIdentityValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class BuiltinImplementationIdentity(ImplementationIdentityValue):
    kind: Literal["builtin"] = "builtin"
    build_digest: str = Field(pattern=_DIGEST_PATTERN)

    def fingerprint_document(self) -> dict[str, object]:
        return {"kind": self.kind, "build_digest": self.build_digest}

    def provenance_document(self) -> dict[str, object]:
        return self.fingerprint_document()


class PluginImplementationIdentity(ImplementationIdentityValue):
    kind: Literal["plugin"] = "plugin"
    plugin_release_pin: SavedGraphPluginReleasePin
    manifest_digest: str = Field(pattern=_DIGEST_PATTERN)
    image_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("plugin_release_pin", mode="before")
    @classmethod
    def validate_pin_shape(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        expected = {"scope", "slug", "revision"}
        if set(value) != expected:
            raise ValueError(
                "Plugin implementation identity pin must contain exactly scope, "
                "slug, and revision"
            )
        return value

    def fingerprint_document(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "plugin_release_pin": {
                "scope": self.plugin_release_pin.scope.value,
                "slug": self.plugin_release_pin.slug,
                "revision": self.plugin_release_pin.revision,
            },
            "manifest_digest": self.manifest_digest,
            "image_digest": self.image_digest,
        }

    def provenance_document(self) -> dict[str, object]:
        return self.fingerprint_document()


ImplementationIdentity = Annotated[
    BuiltinImplementationIdentity | PluginImplementationIdentity,
    Field(discriminator="kind"),
]


def builtin_identity(build_digest: str) -> BuiltinImplementationIdentity:
    return BuiltinImplementationIdentity(build_digest=build_digest)


def plugin_identity(
    *,
    scope: PluginReleaseScope,
    slug: str,
    revision: int,
    manifest_digest: str,
    image_digest: str,
    workspace_id: UUID | None = None,
) -> PluginImplementationIdentity:
    del workspace_id
    return PluginImplementationIdentity(
        plugin_release_pin=SavedGraphPluginReleasePin(
            scope=scope,
            slug=slug,
            revision=revision,
        ),
        manifest_digest=manifest_digest,
        image_digest=image_digest,
    )


__all__ = [
    "BuiltinImplementationIdentity",
    "ImplementationIdentity",
    "PluginImplementationIdentity",
    "builtin_identity",
    "plugin_identity",
]

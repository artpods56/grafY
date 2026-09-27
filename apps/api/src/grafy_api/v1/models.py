from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.plugin_releases import PluginReleaseScope
from grafy_core.domain.saved_graphs import SavedGraphPluginReleasePin


class ApiResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)


class ArtifactTypeKeyResponse(ApiResponse):
    id: str
    schema_version: int = Field(ge=1, strict=True)

    @classmethod
    def from_key(cls, key: ArtifactTypeKey) -> "ArtifactTypeKeyResponse":
        return cls(id=key.id, schema_version=key.schema_version)

    def to_key(self) -> ArtifactTypeKey:
        return ArtifactTypeKey(id=self.id, schema_version=self.schema_version)


ArtifactTypeVariableIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class ArtifactTypeBindingModel(ApiResponse):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        from_attributes=True,
        extra="forbid",
    )

    variable: ArtifactTypeVariableIdentifier
    artifact_type: ArtifactTypeKeyResponse


class PluginReleasePinModel(ApiResponse):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        from_attributes=True,
        extra="forbid",
    )

    scope: PluginReleaseScope
    slug: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    revision: int = Field(ge=1, strict=True)

    @classmethod
    def from_saved_pin(
        cls,
        pin: SavedGraphPluginReleasePin,
    ) -> "PluginReleasePinModel":
        return cls(scope=pin.scope, slug=pin.slug, revision=pin.revision)


__all__ = [
    "ApiResponse",
    "ArtifactTypeBindingModel",
    "ArtifactTypeKeyResponse",
    "ArtifactTypeVariableIdentifier",
    "PluginReleasePinModel",
]

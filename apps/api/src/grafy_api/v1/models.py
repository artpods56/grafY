from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from grafy_core.artifacts import ArtifactTypeKey


class ApiResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)


class ArtifactTypeKeyResponse(ApiResponse):
    id: str
    schema_version: int = Field(ge=1, strict=True)

    @classmethod
    def from_key(cls, key: ArtifactTypeKey) -> "ArtifactTypeKeyResponse":
        return cls(id=key.id, schema_version=key.schema_version)


ArtifactTypeVariableIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


__all__ = [
    "ApiResponse",
    "ArtifactTypeKeyResponse",
    "ArtifactTypeVariableIdentifier",
]

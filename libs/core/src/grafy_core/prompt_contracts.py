from enum import StrEnum
from typing import Self, cast

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import (
    ArtifactPreviewKind,
    ArtifactRef,
    ArtifactReferenceContract,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)


class PromptMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"


class PromptMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: PromptMessageRole
    text: StrictStr
    image_refs: list[ArtifactRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_image_refs(self) -> Self:
        for index, image_ref in enumerate(self.image_refs):
            if image_ref.key() != RASTER_IMAGE.key:
                raise ValueError(
                    f"image_refs[{index}] must reference {RASTER_IMAGE.key.id}@"
                    f"{RASTER_IMAGE.key.schema_version}, got {image_ref.artifact_type}@"
                    f"{image_ref.schema_version}"
                )
        if self.role is PromptMessageRole.SYSTEM and self.image_refs:
            raise ValueError("System prompt messages cannot include images")
        return self


PROMPT_MESSAGE = ArtifactTypeSpec(
    key=ArtifactTypeKey("prompt.message", 2),
    title="Instruction",
    payload_schema=cast(JsonObject, PromptMessage.model_json_schema()),
    references=(
        ArtifactReferenceContract(
            path=("image_refs",),
            target=RASTER_IMAGE.key,
            shape="many",
        ),
    ),
    preview_kind=ArtifactPreviewKind.TEXT,
)


__all__ = [
    "PROMPT_MESSAGE",
    "PromptMessage",
    "PromptMessageRole",
]

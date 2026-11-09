"""Portable metadata describing the exact file set behind an artifact.

A plugin that stores one artifact as several objects declares them here so the
deployment can carry the artifact between storages. Only the declaration lives
in this module; copying the objects themselves is the storage layer's work.
"""

from pathlib import PurePosixPath
from typing import ClassVar, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grafy_core.artifacts import JsonObject


PORTABLE_BUNDLE_METADATA_KEY = "_portable_bundle"


class _PortableValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


def _normalized_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise ValueError("Object-set paths must use POSIX separators")
    path = PurePosixPath(value)
    if (
        value == ""
        or path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Object-set paths must be normalized and relative")
    return path


class PortableArtifactFile(_PortableValue):
    object_key: str = Field(min_length=1, max_length=2_048)
    byte_size: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_object_key(self) -> Self:
        _normalized_path(self.object_key)
        return self


class PortableMetadataReference(_PortableValue):
    path: tuple[str, ...] = Field(min_length=1, max_length=32)
    kind: Literal["bucket", "object", "prefix"]

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if any(part == "" or len(part) > 255 for part in self.path):
            raise ValueError("Portable metadata reference paths must be non-empty")
        return self


class PortableArtifactBundleMetadata(_PortableValue):
    files: tuple[PortableArtifactFile, ...] = Field(min_length=1)
    references: tuple[PortableMetadataReference, ...] = ()

    @model_validator(mode="after")
    def validate_unique_identity(self) -> Self:
        object_keys = [file.object_key for file in self.files]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("Portable artifact files must have unique object keys")
        paths = [reference.path for reference in self.references]
        if len(paths) != len(set(paths)):
            raise ValueError("Portable metadata references must have unique paths")
        return self

    def as_metadata_value(self) -> JsonObject:
        return cast(JsonObject, self.model_dump(mode="json"))


__all__ = [
    "PORTABLE_BUNDLE_METADATA_KEY",
    "PortableArtifactBundleMetadata",
    "PortableArtifactFile",
    "PortableMetadataReference",
]

from datetime import UTC, datetime
from enum import StrEnum

from grafy_core.artifacts import LibraryProvenance
from grafy_core.domain.artifact_outputs import (
    ArtifactOutputValue,
    artifact_outputs_from_storage,
    artifact_outputs_to_storage,
)
from grafy_core.domain.saved_graphs import SavedGraphDocument
from pydantic import BaseModel
from sqlalchemy import (
    JSON,
    DateTime,
    String,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class PydanticJSONType[T: BaseModel](TypeDecorator[T]):
    impl = JSON
    cache_ok = True
    model_type: type[T]

    def process_bind_param(
        self,
        value: T | None,
        dialect: Dialect,
    ) -> dict[str, object] | None:
        del dialect
        return None if value is None else value.model_dump(mode="json")

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> T | None:
        del dialect
        return None if value is None else self.model_type.model_validate(value)


class StringEnumType[E: StrEnum](TypeDecorator[E]):
    impl = String
    cache_ok = True
    enum_type: type[E]

    def process_bind_param(
        self,
        value: E | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else self.enum_type(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> E | None:
        del dialect
        return None if value is None else self.enum_type(value)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class ArtifactOutputsType(
    TypeDecorator[dict[str, ArtifactOutputValue]],
):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: dict[str, ArtifactOutputValue] | None,
        dialect: Dialect,
    ) -> list[dict[str, object]] | None:
        del dialect
        if value is None:
            return None
        return artifact_outputs_to_storage(value)

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> dict[str, ArtifactOutputValue] | None:
        del dialect
        if value is None:
            return None
        return artifact_outputs_from_storage(value)


class SavedGraphDocumentType(PydanticJSONType[SavedGraphDocument]):
    model_type = SavedGraphDocument
    cache_ok = True


class LibraryProvenanceType(PydanticJSONType[LibraryProvenance]):
    # Absent provenance must be SQL NULL. The JSON impl otherwise stores Python
    # None as the JSON literal `null`, which would make every artifact look like
    # a Library item to `library_provenance IS NOT NULL`.
    impl = JSON(none_as_null=True)
    model_type = LibraryProvenance
    cache_ok = True

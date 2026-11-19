import base64
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactExportFormat,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)


type TableValue = (
    StrictStr
    | StrictInt
    | StrictFloat
    | StrictBool
    | None
    | list[TableValue]
    | dict[str, TableValue]
)


class TableValueType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    NUMBER = "number"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    JSON = "json"
    BINARY = "binary"
    UNKNOWN = "unknown"
    MIXED = "mixed"


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1, max_length=255)
    title: StrictStr = Field(max_length=1_024)
    value_type: TableValueType = TableValueType.UNKNOWN

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        if self.id != self.id.strip():
            raise ValueError("Table column id must not have surrounding whitespace")
        return self


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[TableColumn] = Field(max_length=10_000)
    rows: list[dict[str, TableValue]]

    @model_validator(mode="after")
    def validate_shape_and_values(self) -> Self:
        column_ids = [column.id for column in self.columns]
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("Table column ids must be unique")
        expected_ids = set(column_ids)
        columns_by_id = {column.id: column for column in self.columns}
        for row_index, row in enumerate(self.rows):
            actual_ids = set(row)
            missing = sorted(expected_ids - actual_ids)
            extra = sorted(actual_ids - expected_ids)
            if missing or extra:
                details: list[str] = []
                if missing:
                    details.append(f"missing {missing!r}")
                if extra:
                    details.append(f"unexpected {extra!r}")
                raise ValueError(
                    f"Table row {row_index} does not match its columns: "
                    + ", ".join(details)
                )
            for column_id, value in row.items():
                value_type = columns_by_id[column_id].value_type
                if value is not None and not _matches_type(value, value_type):
                    raise ValueError(
                        f"Table row {row_index} column {column_id!r} declares "
                        f"{value_type.value!r} but contains "
                        f"{type(value).__name__}"
                    )
        return self


class TablePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[TableColumn]
    rows: list[dict[str, TableValue]]
    offset: StrictInt = Field(ge=0)
    total_rows: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        Table(columns=self.columns, rows=self.rows)
        if self.offset > self.total_rows:
            raise ValueError("Table page offset must not exceed total rows")
        if self.offset + len(self.rows) > self.total_rows:
            raise ValueError("Table page rows exceed total rows")
        return self


class TableChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: StrictInt = Field(ge=0)
    rows: list[dict[str, TableValue]]


class TableChunkDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: StrictInt = Field(ge=0)
    row_count: StrictInt = Field(ge=1)
    object_key: StrictStr = Field(min_length=1)
    byte_size: StrictInt = Field(ge=0)
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class TableManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal[
        "grafy.table.chunked-json.v1",
        "notarius.table.chunked-json.v1",
    ] = "grafy.table.chunked-json.v1"
    columns: list[TableColumn]
    row_count: StrictInt = Field(ge=0)
    chunks: list[TableChunkDescriptor]

    @model_validator(mode="after")
    def validate_chunks_cover_rows(self) -> Self:
        expected_offset = 0
        for chunk in self.chunks:
            if chunk.offset != expected_offset:
                raise ValueError(
                    f"Table chunk at offset {chunk.offset} must start at "
                    f"{expected_offset}"
                )
            expected_offset += chunk.row_count
        if expected_offset != self.row_count:
            raise ValueError(
                f"Table chunks cover {expected_offset} rows, expected {self.row_count}"
            )
        return self


class TableColumnLookupError(LookupError):
    pass


def resolve_table_column(columns: Sequence[TableColumn], reference: str) -> str:
    """Return the id of the column an exact id or one unique title names."""
    for column in columns:
        if column.id == reference:
            return column.id
    titled = [column.id for column in columns if column.title == reference]
    if len(titled) > 1:
        raise TableColumnLookupError(
            f"Table column title {reference!r} is ambiguous; use one of the "
            f"column ids {titled!r}"
        )
    if not titled:
        raise TableColumnLookupError(f"Table has no column id or title {reference!r}")
    return titled[0]


def _matches_type(value: TableValue, value_type: TableValueType) -> bool:
    if value_type in {TableValueType.UNKNOWN, TableValueType.MIXED}:
        return True
    if value_type is TableValueType.TEXT:
        return isinstance(value, str)
    if value_type is TableValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type is TableValueType.NUMBER:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if value_type is TableValueType.BOOLEAN:
        return isinstance(value, bool)
    if value_type is TableValueType.JSON:
        return isinstance(value, list | dict)
    if not isinstance(value, str):
        return False
    if value_type is TableValueType.DECIMAL:
        try:
            Decimal(value)
        except InvalidOperation:
            return False
        return True
    if value_type is TableValueType.DATE:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if value_type is TableValueType.DATETIME:
        try:
            datetime.fromisoformat(value)
        except ValueError:
            return False
        return True
    if value_type is TableValueType.BINARY:
        try:
            base64.b64decode(value, validate=True)
        except ValueError:
            return False
        return True
    return False


TABLE_DATA = ArtifactTypeSpec(
    key=ArtifactTypeKey("table.data", 1),
    title="Table",
    payload_schema=cast(JsonObject, Table.model_json_schema()),
    bundle=ArtifactBundleContract(format="table-bundle", version=1),
    export_formats=(
        ArtifactExportFormat(
            format="csv",
            content_type="text/csv; charset=utf-8",
            filename="table.csv",
        ),
    ),
)


__all__ = [
    "TABLE_DATA",
    "Table",
    "TableChunk",
    "TableChunkDescriptor",
    "TableColumn",
    "TableColumnLookupError",
    "TableManifest",
    "TablePage",
    "TableValue",
    "TableValueType",
    "resolve_table_column",
]

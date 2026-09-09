import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import ArtifactExportFormat, JsonObject
from grafy_core.spatial_contracts import (
    GeoVectorStyle as StoredGeoVectorStyle,
    GeoRasterStyle as StoredGeoRasterStyle,
    GeoBounds as GeoBounds,
    GeoFeatureCollectionPayload as GeoFeatureCollectionPayload,
    GeoFeatureCollectionMetadata,
    GeoVectorProjectionMetadata as GeoVectorProjectionMetadata,
    GeoRasterProjectionMetadata as GeoRasterProjectionMetadata,
)
from grafy_core.table_contracts import TableColumn, TablePage, TableValueType

from grafy_api.v1.models import ApiResponse


type GeoArtifactKind = Literal[
    "feature_collection",
    "raster_scan",
    "map_layer",
    "map_document",
]


class ArtifactExportFormatResponse(ApiResponse):
    format: str
    content_type: str
    filename: str

    @classmethod
    def from_export_format(cls, export_format: "ArtifactExportFormat") -> "Self":
        return cls(
            format=export_format.format,
            content_type=export_format.content_type,
            filename=export_format.filename,
        )


class ArtifactSummaryResponse(ApiResponse):
    artifact_id: UUID
    artifact_type: str
    schema_version: int
    content_type: str
    byte_size: int | None = None
    sha256: str | None = None
    text: str | None = None
    content_url: str | None = None
    download_formats: list[ArtifactExportFormatResponse] = Field(
        default_factory=list,
    )
    metadata: dict[str, object] = Field(default_factory=dict)


class WorkbenchErrorResponse(ApiResponse):
    detail: str


class TableColumnResponse(ApiResponse):
    id: str
    title: str
    value_type: TableValueType

    @classmethod
    def from_column(cls, column: TableColumn) -> "TableColumnResponse":
        return cls(
            id=column.id,
            title=column.title,
            value_type=column.value_type,
        )


class TableSchemaResponse(ApiResponse):
    columns: list[TableColumnResponse]
    total_rows: int = Field(ge=0)

    @classmethod
    def from_page(cls, page: TablePage) -> "TableSchemaResponse":
        return cls(
            columns=[
                TableColumnResponse.from_column(column) for column in page.columns
            ],
            total_rows=page.total_rows,
        )


class TableCellPreviewResponse(ApiResponse):
    display: str | float | bool | None
    truncated: bool
    original_length: int | None = Field(default=None, ge=0)

    @classmethod
    def from_value(
        cls,
        value: object,
        *,
        max_cell_characters: int,
    ) -> "TableCellPreviewResponse":
        if isinstance(value, int) and not isinstance(value, bool):
            display: str | float | bool | None = str(value)
        elif value is None or isinstance(value, str | float | bool):
            display = value
        else:
            display = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        if not isinstance(display, str) or len(display) <= max_cell_characters:
            return cls(display=display, truncated=False)
        return cls(
            display=display[:max_cell_characters] + "…",
            truncated=True,
            original_length=len(display),
        )


class TablePageResponse(ApiResponse):
    columns: list[TableColumnResponse]
    rows: list[dict[str, TableCellPreviewResponse]]
    row_indices: list[int] = Field(default_factory=list)
    highlighted_row_indices: list[int] = Field(default_factory=list)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total_rows: int = Field(ge=0)
    column_offset: int = Field(ge=0)
    column_limit: int = Field(ge=1)
    total_columns: int = Field(ge=0)

    @classmethod
    def from_page(
        cls,
        page: TablePage,
        *,
        limit: int,
        column_offset: int,
        column_limit: int,
        column_ids: list[str] | None = None,
        max_cell_characters: int,
        row_indices: list[int] | None = None,
        highlighted_row_indices: list[int] | None = None,
    ) -> "TablePageResponse":
        if column_ids is None:
            effective_column_offset = min(column_offset, len(page.columns))
            visible_columns = page.columns[
                effective_column_offset : effective_column_offset + column_limit
            ]
        else:
            columns_by_id = {column.id: column for column in page.columns}
            missing_column_ids = [
                column_id for column_id in column_ids if column_id not in columns_by_id
            ]
            if missing_column_ids:
                raise ValueError(f"Table has no column(s) {missing_column_ids!r}")
            effective_column_offset = 0
            visible_columns = [columns_by_id[column_id] for column_id in column_ids]
        return cls(
            columns=[
                TableColumnResponse.from_column(column) for column in visible_columns
            ],
            rows=[
                {
                    column.id: TableCellPreviewResponse.from_value(
                        row[column.id],
                        max_cell_characters=max_cell_characters,
                    )
                    for column in visible_columns
                }
                for row in page.rows
            ],
            row_indices=(
                row_indices
                if row_indices is not None
                else list(range(page.offset, page.offset + len(page.rows)))
            ),
            highlighted_row_indices=highlighted_row_indices or [],
            offset=page.offset,
            limit=limit,
            total_rows=page.total_rows,
            column_offset=effective_column_offset,
            column_limit=len(visible_columns) if column_ids else column_limit,
            total_columns=len(page.columns),
        )


type ArtifactInteractionScalar = StrictStr | StrictInt | StrictFloat | StrictBool | None


class ArtifactExactMatchRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, ArtifactInteractionScalar] = Field(
        min_length=1,
        max_length=8,
    )

    @field_validator("values")
    @classmethod
    def validate_field_names(
        cls,
        values: dict[str, ArtifactInteractionScalar],
    ) -> dict[str, ArtifactInteractionScalar]:
        for field_name in values:
            if (
                field_name == ""
                or field_name != field_name.strip()
                or len(field_name) > 255
            ):
                raise ValueError(
                    "Table exact-match field names must be non-empty, trimmed, "
                    "and at most 255 characters"
                )
        return values


class TableExactMatchGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ArtifactExactMatchRow] = Field(min_length=1, max_length=50)


class TableQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_groups: list[TableExactMatchGroup] = Field(
        default_factory=list,
        max_length=8,
    )
    highlight_groups: list[TableExactMatchGroup] = Field(
        default_factory=list,
        max_length=8,
    )
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=50, ge=1, le=100)
    column_offset: StrictInt = Field(default=0, ge=0)
    column_limit: StrictInt = Field(default=25, ge=1, le=100)
    column_ids: list[Annotated[str, Field(min_length=1, max_length=255)]] | None = (
        Field(default=None, min_length=1, max_length=100)
    )
    max_cell_characters: StrictInt = Field(default=256, ge=32, le=2_000)


class TableCellResponse(ApiResponse):
    row_index: int = Field(ge=0)
    column_id: str
    value: str | float | bool | None
    encoding: Literal["native", "integer", "json"] = "native"

    @classmethod
    def from_value(
        cls,
        *,
        row_index: int,
        column_id: str,
        value: object,
    ) -> "TableCellResponse":
        if isinstance(value, int) and not isinstance(value, bool):
            response_value: str | float | bool | None = str(value)
            encoding: Literal["native", "integer", "json"] = "integer"
        elif value is None or isinstance(value, str | float | bool):
            response_value = value
            encoding = "native"
        else:
            response_value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            encoding = "json"
        return cls(
            row_index=row_index,
            column_id=column_id,
            value=response_value,
            encoding=encoding,
        )


class StrictGeoModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


type GeoPropertyValueType = Literal[
    "text",
    "integer",
    "number",
    "boolean",
    "null",
    "mixed",
    "unknown",
]


class GeoPropertyFieldResponse(ApiResponse):
    id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=1_024)
    value_type: GeoPropertyValueType


class GeoArtifactRefPayload(StrictGeoModel):
    artifact_id: UUID
    artifact_type: StrictStr = Field(min_length=1)
    schema_version: StrictInt = Field(ge=1)
    content_hash: StrictStr | None = None


class GeoFeatureManifestMetadata(GeoFeatureCollectionMetadata):
    property_fields: list[GeoPropertyFieldResponse] = Field(
        default_factory=list,
    )


class GeoFeatureArtifactSourcePayload(StrictGeoModel):
    kind: Literal["feature_collection"]
    artifact: GeoArtifactRefPayload


class GeoRasterArtifactSourcePayload(StrictGeoModel):
    kind: Literal["raster_scan"]
    artifact: GeoArtifactRefPayload


class GeoWmsSourcePayload(StrictGeoModel):
    kind: Literal["wms"]
    url: AnyHttpUrl
    layer: StrictStr = Field(min_length=1, max_length=1_024)
    version: Literal["1.1.1", "1.3.0"]
    format: Literal["image/png", "image/jpeg"]
    bounds: GeoBounds
    attribution: StrictStr = Field(min_length=1, max_length=4_096)
    style_name: StrictStr | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def reject_embedded_credentials(self) -> Self:
        if self.url.username is not None or self.url.password is not None:
            raise ValueError("WMS URL must not contain embedded credentials")
        return self


GeoLayerSourcePayload = Annotated[
    GeoFeatureArtifactSourcePayload
    | GeoRasterArtifactSourcePayload
    | GeoWmsSourcePayload,
    Field(discriminator="kind"),
]


class GeoFillStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    opacity: float = Field(ge=0.0, le=1.0)


class GeoLineStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    opacity: float = Field(ge=0.0, le=1.0)
    width: float = Field(ge=0.0, le=64.0)


class GeoPointStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    opacity: float = Field(ge=0.0, le=1.0)
    radius: float = Field(ge=0.0, le=128.0)
    stroke_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    stroke_width: float = Field(ge=0.0, le=32.0)


type GeoCategoryValue = StrictStr | StrictInt | StrictFloat | StrictBool


class GeoPointCategory(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    )
    title: StrictStr = Field(min_length=1, max_length=1_024)
    values: list[GeoCategoryValue] = Field(min_length=1, max_length=128)
    point: GeoPointStyle
    min_zoom: StrictInt = Field(ge=0, le=24)
    max_zoom: StrictInt = Field(ge=0, le=24)

    @model_validator(mode="after")
    def validate_category(self) -> Self:
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom")
        typed_values = [(type(value), value) for value in self.values]
        if len(typed_values) != len(set(typed_values)):
            raise ValueError("category values must be unique")
        return self


class GeoLabelStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    property: str = Field(min_length=1, max_length=1_024)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    size: float = Field(ge=6.0, le=72.0)
    halo_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    halo_width: float = Field(ge=0.0, le=16.0)


class GeoVectorStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vector"]
    fill: GeoFillStyle
    line: GeoLineStyle
    outline: GeoLineStyle
    point: GeoPointStyle
    label: GeoLabelStyle | None

    @classmethod
    def default(cls) -> "GeoVectorStyle":
        return cls.model_validate(StoredGeoVectorStyle())


class GeoCategorizedPointStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["categorized_points"]
    category_property: StrictStr = Field(min_length=1, max_length=1_024)
    categories: list[GeoPointCategory] = Field(min_length=1, max_length=128)
    label: GeoLabelStyle | None

    @field_validator("category_property")
    @classmethod
    def validate_category_property(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("category property must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_categories(self) -> Self:
        category_ids = [category.id for category in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("category ids must be unique")
        observed_values: set[tuple[type[object], object]] = set()
        for category in self.categories:
            for value in category.values:
                key = (type(value), value)
                if key in observed_values:
                    raise ValueError(
                        "category values must not appear in multiple categories"
                    )
                observed_values.add(key)
        return self


class GeoRasterStyle(ApiResponse):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raster"]
    opacity: float = Field(ge=0.0, le=1.0)
    brightness_min: float = Field(ge=0.0, le=1.0)
    brightness_max: float = Field(ge=0.0, le=1.0)
    contrast: float = Field(ge=-1.0, le=1.0)
    saturation: float = Field(ge=-1.0, le=1.0)
    hue: float = Field(ge=0.0, le=359.0)
    resampling: Literal["linear", "nearest"]

    @model_validator(mode="after")
    def validate_brightness_range(self) -> Self:
        if self.brightness_min > self.brightness_max:
            raise ValueError("brightness_min must not exceed brightness_max")
        return self

    @classmethod
    def default(cls) -> "GeoRasterStyle":
        return cls.model_validate(StoredGeoRasterStyle())


GeoLayerStyle = Annotated[
    GeoVectorStyle | GeoCategorizedPointStyle | GeoRasterStyle,
    Field(discriminator="kind"),
]


class GeoMapLayerPayload(StrictGeoModel):
    title: StrictStr = Field(min_length=1, max_length=1_024)
    visible: bool
    opacity: float = Field(ge=0.0, le=1.0)
    min_zoom: StrictInt = Field(ge=0, le=24)
    max_zoom: StrictInt = Field(ge=0, le=24)
    source: GeoLayerSourcePayload
    style: GeoLayerStyle

    @model_validator(mode="after")
    def validate_source_and_style(self) -> Self:
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom")
        if self.source.kind == "feature_collection" and self.style.kind not in {
            "vector",
            "categorized_points",
        }:
            raise ValueError("Feature collection sources require vector style")
        if self.style.kind == "categorized_points":
            for category in self.style.categories:
                if max(self.min_zoom, category.min_zoom) > min(
                    self.max_zoom,
                    category.max_zoom,
                ):
                    raise ValueError(
                        f"Category {category.id!r} zoom range does not overlap "
                        "the layer zoom range"
                    )
        if self.source.kind in {"raster_scan", "wms"} and self.style.kind != "raster":
            raise ValueError("Raster scan and WMS sources require raster style")
        return self


class GeoMapDocumentPayload(StrictGeoModel):
    layers: list[GeoArtifactRefPayload] = Field(min_length=1)
    basemap: Literal["openstreetmap", "none"]
    initial_bounds: GeoBounds | None

    @model_validator(mode="after")
    def validate_unique_layer_refs(self) -> Self:
        ids = [layer.artifact_id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("Geo map document layer references must be unique")
        return self


class GeoVectorRenderSourceResponse(ApiResponse):
    kind: Literal["vector"] = "vector"
    artifact_id: UUID
    archive_url: str
    source_layer: str
    bounds: GeoBounds | None
    min_zoom: int = Field(ge=0, le=24)
    max_zoom: int = Field(ge=0, le=24)
    fields: list[GeoPropertyFieldResponse] = Field(default_factory=list)


class GeoRasterRenderSourceResponse(ApiResponse):
    kind: Literal["raster"] = "raster"
    artifact_id: UUID | None
    tilejson_url: str
    bounds: GeoBounds
    attribution: str | None = None


GeoRenderSourceResponse = Annotated[
    GeoVectorRenderSourceResponse | GeoRasterRenderSourceResponse,
    Field(discriminator="kind"),
]


class GeoRenderLayerResponse(ApiResponse):
    id: str
    title: str
    visible: bool
    opacity: float = Field(ge=0.0, le=1.0)
    min_zoom: int = Field(ge=0, le=24)
    max_zoom: int = Field(ge=0, le=24)
    source: GeoRenderSourceResponse
    style: GeoLayerStyle


class GeoRenderResponse(ApiResponse):
    artifact_id: UUID
    kind: GeoArtifactKind
    basemap: Literal["openstreetmap", "none"]
    initial_bounds: GeoBounds | None
    layers: list[GeoRenderLayerResponse]


class GeoExactFeatureResponse(ApiResponse):
    source_artifact_id: UUID
    feature_index: int = Field(ge=0)
    feature: JsonObject


class GeoFeatureQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ArtifactExactMatchRow] = Field(min_length=1, max_length=50)


class GeoFeatureQueryResponse(ApiResponse):
    artifact_id: UUID
    bounds: GeoBounds | None
    matched_feature_count: int = Field(ge=0)
    source_artifact_ids: list[UUID]


class GeoRasterTileJsonResponse(ApiResponse):
    tilejson: Literal["3.0.0"] = "3.0.0"
    name: str
    tiles: list[str] = Field(min_length=1)
    bounds: GeoBounds
    minzoom: int = Field(ge=0, le=24)
    maxzoom: int = Field(ge=0, le=24)
    attribution: str | None = None
    scheme: Literal["xyz"] = "xyz"


__all__ = [
    "ArtifactExportFormatResponse",
    "ArtifactSummaryResponse",
    "ArtifactExactMatchRow",
    "GeoArtifactRefPayload",
    "GeoCategorizedPointStyle",
    "GeoExactFeatureResponse",
    "GeoFeatureCollectionPayload",
    "GeoFeatureQueryRequest",
    "GeoFeatureQueryResponse",
    "GeoFeatureManifestMetadata",
    "GeoMapDocumentPayload",
    "GeoMapLayerPayload",
    "GeoPointCategory",
    "GeoPropertyFieldResponse",
    "GeoRasterProjectionMetadata",
    "GeoRasterRenderSourceResponse",
    "GeoRasterStyle",
    "GeoRasterTileJsonResponse",
    "GeoRenderLayerResponse",
    "GeoRenderResponse",
    "GeoVectorProjectionMetadata",
    "GeoVectorRenderSourceResponse",
    "GeoVectorStyle",
    "GeoWmsSourcePayload",
    "TableCellPreviewResponse",
    "TableCellResponse",
    "TableColumnResponse",
    "TableExactMatchGroup",
    "TablePageResponse",
    "TableQueryRequest",
    "TableSchemaResponse",
    "WorkbenchErrorResponse",
]

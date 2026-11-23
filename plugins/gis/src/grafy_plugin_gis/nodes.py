import json
from collections.abc import Callable
from typing import Annotated, Self, cast, final, override

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.config_ui import field_ui
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.egress import validated_public_destination
from grafy_core.documents import GeoJsonFile, JsonFile, TiffFile
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    Plugs,
    Ref,
    RefSequence,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeHttpEgressContract,
    NodeHttpEgressInput,
)
from grafy_core.runtime.artifact_values import inline_model_artifact
from grafy_core.table_contracts import (
    Table,
    TableColumn,
    TableColumnLookupError,
    TableValue,
    TableValueType,
    resolve_table_column,
)
from pydantic import (
    AnyHttpUrl,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from pyproj import CRS, Transformer
from shapely import (
    from_geojson,  # pyright: ignore[reportUnknownVariableType]
    from_wkt,  # pyright: ignore[reportUnknownVariableType]
    to_geojson,  # pyright: ignore[reportUnknownVariableType]
    to_wkt,  # pyright: ignore[reportUnknownVariableType]
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from grafy_plugin_gis.artifacts import GEO_MAP_DOCUMENT, GEO_MAP_LAYER
from grafy_plugin_gis.declaration import GIS
from grafy_plugin_gis.persistence import (
    feature_collection_artifact,
    raster_scan_artifact,
)
from grafy_core.spatial_contracts import (
    MAX_RASTER_MOSAIC_SOURCES,
    BasemapKind,
    Bounds,
    GeoFeatureArtifactSource,
    GeoFeatureCollection,
    GeoFeatureStyle,
    GeoMapDocument,
    GeoMapLayer,
    GeoRasterArtifactSource,
    GeoRasterMosaicSource,
    GeoRasterStyle,
    GeoVectorStyle,
    GeoWmsSource,
    WmsImageFormat,
    WmsVersion,
)
from grafy_plugin_gis.models import (
    GeoRasterScan,
)
from grafy_plugin_gis.wfs import (
    WFS_IMPORT_MAX_FEATURES,
    WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES,
    WfsClient,
)

import grafy_core.documents as _documents
import grafy_workbench.table.plugin as _table_plugin

_ = (_documents.__name__, _table_plugin.__name__)  # notes classes before these ports


_HANDLE_READ_LIMIT = 256 * 1024 * 1024

GIS.register(feature_collection_artifact())
GIS.register(raster_scan_artifact())
GIS.register(inline_model_artifact(GEO_MAP_LAYER, GeoMapLayer))
GIS.register(inline_model_artifact(GEO_MAP_DOCUMENT, GeoMapDocument))

_parse_wkt = cast(Callable[[str], BaseGeometry], from_wkt)
_parse_geojson = cast(Callable[[str], BaseGeometry], from_geojson)
_serialize_geojson = cast(Callable[[BaseGeometry], str], to_geojson)
_serialize_wkt = cast(Callable[..., str], to_wkt)
_parse_crs = cast(Callable[[str], CRS], CRS.from_user_input)


class GeoJsonParseError(RuntimeError):
    pass


class GeoRasterScanImportError(RuntimeError):
    pass


class TableToGeoFeaturesError(RuntimeError):
    pass


class GeoFeaturesToTableError(RuntimeError):
    pass


class GeoFeaturesToTableConfig(NodeConfig):
    geometry_column: StrictStr = Field(
        default="geometry_wkt",
        min_length=1,
        max_length=255,
        description="Output table column containing exact WGS84 WKT geometry.",
    )
    feature_id_column: StrictStr | None = Field(
        default="feature_id",
        min_length=1,
        max_length=255,
        description="Optional output table column containing the GeoJSON feature id.",
    )

    @field_validator("geometry_column", "feature_id_column")
    @classmethod
    def validate_column_name(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("column names must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_distinct_columns(self) -> Self:
        if self.feature_id_column == self.geometry_column:
            raise ValueError("feature id and geometry columns must be distinct")
        return self


class GeoFeaturesToTableInput(NodeInput):
    features: Annotated[
        GeoFeatureCollection,
        Field(description="Exact WGS84 GeoJSON feature collection."),
    ]


class GeoFeaturesToTableOutput(NodeOutput):
    table: Annotated[
        Table,
        Field(description="Feature ids, properties, and exact WGS84 WKT geometry."),
    ]


def _table_value_type(values: list[TableValue]) -> TableValueType:
    observed: set[TableValueType] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            observed.add(TableValueType.BOOLEAN)
        elif isinstance(value, int):
            observed.add(TableValueType.INTEGER)
        elif isinstance(value, float):
            observed.add(TableValueType.NUMBER)
        elif isinstance(value, str):
            observed.add(TableValueType.TEXT)
        else:
            observed.add(TableValueType.JSON)
    if not observed:
        return TableValueType.UNKNOWN
    if observed <= {TableValueType.INTEGER, TableValueType.NUMBER}:
        if observed == {TableValueType.INTEGER}:
            return TableValueType.INTEGER
        return TableValueType.NUMBER
    if len(observed) == 1:
        return next(iter(observed))
    return TableValueType.MIXED


@GIS.function_node(
    operator_id="gis.features.to_table",
    version=1,
    title="Geo features to table",
    cache_policy=NodeCachePolicy.EXACT,
)
async def geo_features_to_table(
    config: GeoFeaturesToTableConfig,
    inputs: GeoFeaturesToTableInput,
) -> GeoFeaturesToTableOutput:
    """Turns map places into a table, and keeps each place's location."""
    property_ids: list[str] = []
    properties_by_feature: list[dict[str, TableValue]] = []
    for feature_index, feature in enumerate(inputs.features.features):
        raw_properties = feature.get("properties")
        if raw_properties is None:
            properties: dict[str, TableValue] = {}
        elif isinstance(raw_properties, dict):
            properties = cast(dict[str, TableValue], raw_properties)
        else:
            raise GeoFeaturesToTableError(
                f"Feature {feature_index} properties must be an object or null"
            )
        for property_id in properties:
            if property_id not in property_ids:
                property_ids.append(property_id)
        properties_by_feature.append(properties)

    reserved_columns = {config.geometry_column}
    if config.feature_id_column is not None:
        reserved_columns.add(config.feature_id_column)
    collisions = sorted(reserved_columns.intersection(property_ids))
    if collisions:
        raise GeoFeaturesToTableError(
            "GeoJSON properties collide with configured output columns "
            f"{collisions!r}; choose different column names"
        )

    rows: list[dict[str, TableValue]] = []
    for feature_index, (feature, properties) in enumerate(
        zip(inputs.features.features, properties_by_feature, strict=True)
    ):
        row: dict[str, TableValue] = {}
        if config.feature_id_column is not None:
            feature_id = feature.get("id")
            if feature_id is not None and (
                isinstance(feature_id, bool) or not isinstance(feature_id, str | int)
            ):
                raise GeoFeaturesToTableError(
                    f"Feature {feature_index} id must be text, integer, or null"
                )
            row[config.feature_id_column] = feature_id
        for property_id in property_ids:
            row[property_id] = properties.get(property_id)

        raw_geometry = feature.get("geometry")
        if raw_geometry is None:
            geometry_wkt = None
        else:
            try:
                geometry = _parse_geojson(
                    json.dumps(
                        raw_geometry,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                geometry_wkt = _serialize_wkt(
                    geometry,
                    rounding_precision=-1,
                    trim=True,
                )
            except Exception as exc:
                raise GeoFeaturesToTableError(
                    f"Feature {feature_index} geometry could not be converted to WKT"
                ) from exc
        row[config.geometry_column] = geometry_wkt
        rows.append(row)

    columns: list[TableColumn] = []
    if config.feature_id_column is not None:
        columns.append(
            TableColumn(
                id=config.feature_id_column,
                title="Feature id",
                value_type=_table_value_type(
                    [row[config.feature_id_column] for row in rows]
                ),
            )
        )
    for property_id in property_ids:
        columns.append(
            TableColumn(
                id=property_id,
                title=property_id,
                value_type=_table_value_type([row[property_id] for row in rows]),
            )
        )
    columns.append(
        TableColumn(
            id=config.geometry_column,
            title="WGS84 geometry (WKT)",
            value_type=TableValueType.TEXT,
        )
    )
    try:
        table = Table(columns=columns, rows=rows)
    except ValueError as exc:
        raise GeoFeaturesToTableError(
            "Feature collection could not be represented as a table"
        ) from exc
    return GeoFeaturesToTableOutput(table=table)


class TableToGeoFeaturesConfig(NodeConfig):
    geometry_column: StrictStr = Field(
        min_length=1,
        description="Table column id or unique title containing exact WKT geometry.",
    )
    source_crs: StrictStr = Field(
        min_length=1,
        description="Source coordinate reference system, for example EPSG:3857.",
    )
    feature_id_column: StrictStr | None = Field(
        default=None,
        description="Optional table column id or unique title used as the GeoJSON feature id.",
    )
    source_name: StrictStr = Field(
        default="Table features",
        min_length=1,
        max_length=1_024,
        description="Human-readable source name.",
    )

    @field_validator(
        "geometry_column", "source_crs", "feature_id_column", "source_name"
    )
    @classmethod
    def validate_non_whitespace(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("values must not have surrounding whitespace")
        return value


class TableToGeoFeaturesInput(NodeInput):
    table: Annotated[
        Table,
        Field(description="Generic table containing one WKT geometry per row."),
    ]


class TableToGeoFeaturesOutput(NodeOutput):
    features: Annotated[
        GeoFeatureCollection,
        Field(description="Exact WGS84 GeoJSON features created from table rows."),
    ]


@GIS.function_node(
    operator_id="gis.table.to_features",
    version=1,
    title="Table to geo features",
    cache_policy=NodeCachePolicy.EXACT,
)
async def table_to_geo_features(
    config: TableToGeoFeaturesConfig,
    inputs: TableToGeoFeaturesInput,
) -> TableToGeoFeaturesOutput:
    """Parses exact table WKT geometries and normalizes them to WGS84."""
    columns = inputs.table.columns
    try:
        geometry_column = resolve_table_column(columns, config.geometry_column)
        feature_id_column = None
        if config.feature_id_column is not None:
            feature_id_column = resolve_table_column(columns, config.feature_id_column)
    except TableColumnLookupError as exc:
        raise TableToGeoFeaturesError(str(exc)) from exc
    try:
        source_crs = _parse_crs(config.source_crs)
        transformer = Transformer.from_crs(
            source_crs,
            CRS.from_epsg(4326),
            always_xy=True,
        )
    except Exception as exc:
        raise TableToGeoFeaturesError(
            f"Invalid source CRS {config.source_crs!r}"
        ) from exc

    features: list[JsonObject] = []
    for row_index, row in enumerate(inputs.table.rows):
        raw_geometry = row[geometry_column]
        geometry: JsonObject | None = None
        if raw_geometry is not None:
            if not isinstance(raw_geometry, str):
                raise TableToGeoFeaturesError(
                    f"Table row {row_index} geometry column "
                    f"{config.geometry_column!r} must contain WKT text or null"
                )
            try:
                parsed = _parse_wkt(raw_geometry)
                if parsed.is_empty:
                    raise ValueError("geometry is empty")
                projected = transform(transformer.transform, parsed)
                geometry = cast(JsonObject, json.loads(_serialize_geojson(projected)))
            except Exception as exc:
                raise TableToGeoFeaturesError(
                    f"Failed to convert WKT in table row {row_index}, geometry "
                    f"column {config.geometry_column!r}: {exc}"
                ) from exc

        properties: JsonObject = {
            column.id: row[column.id]
            for column in inputs.table.columns
            if column.id not in {geometry_column, feature_id_column}
        }
        feature: JsonObject = {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }
        if feature_id_column is not None:
            feature_id = row[feature_id_column]
            if feature_id is not None and not isinstance(feature_id, str | int):
                raise TableToGeoFeaturesError(
                    f"Table row {row_index} feature id column "
                    f"{config.feature_id_column!r} must contain text, integer, or null"
                )
            if feature_id is not None:
                feature["id"] = feature_id
        features.append(feature)

    try:
        collection = GeoFeatureCollection.from_features(features, config.source_name)
    except ValueError as exc:
        raise TableToGeoFeaturesError(
            f"Converted table contains invalid WGS84 geometry: {exc}"
        ) from exc
    return TableToGeoFeaturesOutput(features=collection)


class GeoJsonParseInput(NodeInput):
    file: Annotated[
        GeoJsonFile | JsonFile,
        Field(description="GeoJSON document artifact to parse."),
    ]


class GeoJsonParseOutput(NodeOutput):
    features: Annotated[
        GeoFeatureCollection,
        Field(description="Validated exact WGS84 GeoJSON FeatureCollection."),
    ]


@GIS.node(
    operator_id="gis.geojson.parse",
    version=1,
    title="Parse GeoJSON",
)
@final
class ParseGeoJsonNode(Node[NodeConfig, GeoJsonParseInput, GeoJsonParseOutput]):
    """Parse one persisted GeoJSON document into an exact WGS84 collection."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: GeoJsonParseInput,
        /,
    ) -> GeoJsonParseOutput:
        del context
        content = await inputs.file.read(max_bytes=_HANDLE_READ_LIMIT)
        source_name = inputs.file.filename or "this file"
        try:
            features = GeoFeatureCollection.from_geojson_bytes(
                content,
                source_name,
            )
        except ValueError as exc:
            raise GeoJsonParseError(str(exc)) from exc
        return GeoJsonParseOutput(features=features)


class GeoRasterScanImportConfig(NodeConfig):
    source_name: StrictStr = Field(
        min_length=1,
        max_length=1_024,
        description="Display name of the georeferenced raster scan.",
    )

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("source_name must not have surrounding whitespace")
        return value


class GeoRasterScanImportInput(NodeInput):
    file: Annotated[
        TiffFile,
        Field(description="Georeferenced TIFF file artifact to import."),
    ]


class GeoRasterScanImportOutput(NodeOutput):
    raster: Annotated[
        GeoRasterScan,
        Field(description="Georeferenced raster normalized to COG during persistence."),
    ]


@GIS.node(
    operator_id="gis.raster_scan.import",
    version=1,
    title="Import raster scan",
    cache_policy=NodeCachePolicy.EXACT,
    required_capabilities=(PluginRuntimeCapability.NATIVE_GDAL,),
)
@final
class ImportRasterScanNode(
    Node[GeoRasterScanImportConfig, GeoRasterScanImportInput, GeoRasterScanImportOutput]
):
    """Import one persisted GeoTIFF file artifact as a georeferenced scan."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: GeoRasterScanImportConfig,
        inputs: GeoRasterScanImportInput,
        /,
    ) -> GeoRasterScanImportOutput:
        del context
        content = await inputs.file.read(max_bytes=_HANDLE_READ_LIMIT)
        label = inputs.file.filename or "this file"
        try:
            return GeoRasterScanImportOutput(
                raster=GeoRasterScan(
                    content=content,
                    filename=inputs.file.filename or config.source_name,
                    source_name=config.source_name,
                )
            )
        except ValueError as exc:
            raise GeoRasterScanImportError(
                f"GeoTIFF file {label} cannot be imported as raster "
                f"scan {config.source_name!r}: {exc}"
            ) from exc


class WfsImportConfig(NodeConfig):
    service_url: AnyHttpUrl
    type_name: StrictStr = Field(min_length=1, max_length=1_024)
    source_name: StrictStr = Field(min_length=1, max_length=1_024)
    bbox: Bounds | None = None
    sort_by: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=1_024,
        description="Optional WFS SortBy expression for deterministic paging.",
    )
    page_size: StrictInt = Field(default=1_000, ge=1, le=10_000)
    max_features: StrictInt = Field(
        default=10_000,
        ge=1,
        le=WFS_IMPORT_MAX_FEATURES,
        description=(
            "Required total feature limit for one import; first-release WFS imports "
            f"accept at most {WFS_IMPORT_MAX_FEATURES:,} features."
        ),
    )
    max_page_bytes: StrictInt = Field(
        default=16 * 1024 * 1024,
        ge=1_024,
        le=WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES,
        description=(
            "Maximum response bytes for one WFS page; the complete import also "
            f"has a fixed {WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES}-byte wire limit."
        ),
    )
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)

    @field_validator("service_url")
    @classmethod
    def validate_service_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        return validated_public_destination(value, service_name="WFS")

    @field_validator("max_features", mode="before")
    @classmethod
    def validate_bounded_max_features(cls, value: object) -> object:
        if value is None:
            raise ValueError(
                "max_features must be set; unbounded WFS imports are not supported"
            )
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > WFS_IMPORT_MAX_FEATURES
        ):
            raise ValueError(
                "max_features must not exceed the first-release limit of "
                f"{WFS_IMPORT_MAX_FEATURES}"
            )
        return value

    @field_validator("type_name", "source_name", "sort_by")
    @classmethod
    def validate_non_whitespace(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("values must not have surrounding whitespace")
        return value


class WfsImportInput(NodeInput):
    pass


class WfsImportOutput(NodeOutput):
    features: Annotated[
        GeoFeatureCollection,
        Field(description="Bounded WGS84 feature collection imported through WFS 2.0."),
    ]


@GIS.node(
    operator_id="gis.wfs.import",
    version=1,
    title="Import OGC WFS features",
    factory=lambda _context: ImportWfsNode(WfsClient()),
    required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="service_url"),),
    ),
    cache_policy=NodeCachePolicy.NEVER,
)
@final
class ImportWfsNode(Node[WfsImportConfig, WfsImportInput, WfsImportOutput]):
    """Loads map places from an online map service, inside the area you set."""

    def __init__(self, client: WfsClient) -> None:
        self._client = client

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: WfsImportConfig,
        _inputs: WfsImportInput,
        /,
    ) -> WfsImportOutput:
        await context.progress("Fetching feature collection..")

        features = await self._client.fetch_feature_collection(
            service_url=str(config.service_url),
            type_name=config.type_name,
            source_name=config.source_name,
            page_size=config.page_size,
            max_features=config.max_features,
            max_page_bytes=config.max_page_bytes,
            timeout_seconds=config.timeout_seconds,
            bbox=config.bbox,
            sort_by=config.sort_by,
        )
        return WfsImportOutput(features=features)


class _CommonLayerConfig(NodeConfig):
    title: StrictStr = Field(min_length=1, max_length=1_024)
    visible: bool = Field(default=True, json_schema_extra=field_ui(widget="switch"))
    opacity: float = Field(
        default=1.0, ge=0.0, le=1.0, json_schema_extra=field_ui(widget="slider")
    )
    min_zoom: StrictInt = Field(
        default=0, ge=0, le=24, json_schema_extra=field_ui(advanced=True)
    )
    max_zoom: StrictInt = Field(
        default=22, ge=0, le=24, json_schema_extra=field_ui(advanced=True)
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("title must not have surrounding whitespace")
        return value


class VectorLayerConfig(_CommonLayerConfig):
    style: GeoFeatureStyle = Field(
        default_factory=GeoVectorStyle,
        json_schema_extra=field_ui(
            widget="segmented",
            enum_labels={"vector": "Uniform", "categorized_points": "Categories"},
        ),
    )


class VectorLayerInput(NodeInput):
    features: Annotated[
        Ref[GeoFeatureCollection],
        Field(description="Exact feature collection artifact reference."),
    ]


class MapLayerOutput(NodeOutput):
    layer: Annotated[
        GeoMapLayer,
        Field(description="Lightweight map layer."),
    ]


@GIS.function_node(
    operator_id="gis.map.vector_layer",
    version=1,
    title="Vector map layer",
    cache_policy=NodeCachePolicy.EXACT,
)
async def build_vector_layer(
    config: VectorLayerConfig,
    inputs: VectorLayerInput,
) -> MapLayerOutput:
    """Turn a feature collection into a styled vector map layer."""

    return MapLayerOutput(
        layer=GeoMapLayer(
            title=config.title,
            visible=config.visible,
            opacity=config.opacity,
            min_zoom=config.min_zoom,
            max_zoom=config.max_zoom,
            source=GeoFeatureArtifactSource(artifact=inputs.features),
            style=config.style,
        )
    )


class RasterLayerConfig(_CommonLayerConfig):
    style: GeoRasterStyle = Field(default_factory=GeoRasterStyle)


class RasterLayerInput(NodeInput):
    raster: Annotated[
        Ref[GeoRasterScan] | Ref[TiffFile],
        Field(description="Georeferenced raster scan or TIFF file artifact reference."),
    ]


def _plain_ref(ref: ArtifactRef) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=ref.artifact_id,
        artifact_type=ref.artifact_type,
        schema_version=ref.schema_version,
        content_hash=ref.content_hash,
    )


@GIS.function_node(
    operator_id="gis.map.raster_layer",
    version=1,
    title="Raster map layer",
    cache_policy=NodeCachePolicy.EXACT,
)
async def build_raster_layer(
    config: RasterLayerConfig,
    inputs: RasterLayerInput,
) -> MapLayerOutput:
    """Turn a georeferenced raster scan or TIFF into a styled map layer."""

    return MapLayerOutput(
        layer=GeoMapLayer(
            title=config.title,
            visible=config.visible,
            opacity=config.opacity,
            min_zoom=config.min_zoom,
            max_zoom=config.max_zoom,
            source=GeoRasterArtifactSource(artifact=_plain_ref(inputs.raster)),
            style=config.style,
        )
    )


class RasterMosaicConfig(_CommonLayerConfig):
    title: StrictStr = Field(default="Raster mosaic", min_length=1, max_length=1_024)
    style: GeoRasterStyle = Field(default_factory=GeoRasterStyle)


class RasterMosaicInput(NodeInput):
    rasters: Annotated[
        list[
            Ref[TiffFile]
            | Ref[GeoRasterScan]
            | RefSequence[TiffFile]
            | RefSequence[GeoRasterScan]
        ],
        Plugs(variadic=True, instance=True),
        Field(
            min_length=1,
            title="Rasters",
            description=(
                "Georeferenced TIFF files, raster scans, or lists of them, "
                "stacked bottom to top on the fly by the tiler."
            ),
        ),
    ]


@GIS.function_node(
    operator_id="gis.map.raster_mosaic",
    version=1,
    title="Raster mosaic layer",
    cache_policy=NodeCachePolicy.EXACT,
)
async def build_raster_mosaic(
    config: RasterMosaicConfig,
    inputs: RasterMosaicInput,
) -> MapLayerOutput:
    """Compose georeferenced rasters into one on-the-fly mosaic map layer."""

    refs: list[ArtifactRef] = []
    seen: set[object] = set()
    for entry in inputs.rasters:
        items = entry.item_refs if isinstance(entry, ArtifactRefSequence) else [entry]
        for item in items:
            if item.artifact_id in seen:
                raise UserFacingNodeError(
                    f"Raster artifact {item.artifact_id} is connected more than once."
                )
            seen.add(item.artifact_id)
            refs.append(_plain_ref(item))
    if not refs:
        raise UserFacingNodeError(
            "Raster mosaic requires at least one georeferenced TIFF or raster scan."
        )
    if len(refs) > MAX_RASTER_MOSAIC_SOURCES:
        raise UserFacingNodeError(
            f"Raster mosaic supports at most {MAX_RASTER_MOSAIC_SOURCES} rasters, "
            f"got {len(refs)}."
        )
    return MapLayerOutput(
        layer=GeoMapLayer(
            title=config.title,
            visible=config.visible,
            opacity=config.opacity,
            min_zoom=config.min_zoom,
            max_zoom=config.max_zoom,
            source=GeoRasterMosaicSource(artifacts=refs),
            style=config.style,
        )
    )


class WmsLayerConfig(_CommonLayerConfig):
    url: AnyHttpUrl
    layer: StrictStr = Field(min_length=1, max_length=1_024)
    version: WmsVersion = "1.3.0"
    format: WmsImageFormat = "image/png"
    bounds: Bounds
    attribution: StrictStr = Field(min_length=1, max_length=4_096)
    style_name: StrictStr | None = Field(default=None, max_length=1_024)
    style: GeoRasterStyle = Field(default_factory=GeoRasterStyle)

    @field_validator("url")
    @classmethod
    def validate_service_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        return validated_public_destination(value, service_name="WMS")


class WmsLayerInput(NodeInput):
    pass


@GIS.function_node(
    operator_id="gis.map.wms_layer",
    version=1,
    title="Remote WMS map layer",
    cache_policy=NodeCachePolicy.EXACT,
)
async def build_wms_layer(
    config: WmsLayerConfig,
    _inputs: WmsLayerInput,
) -> MapLayerOutput:
    """Describe a bounded remote WMS source as a raster map layer."""

    return MapLayerOutput(
        layer=GeoMapLayer(
            title=config.title,
            visible=config.visible,
            opacity=config.opacity,
            min_zoom=config.min_zoom,
            max_zoom=config.max_zoom,
            source=GeoWmsSource(
                url=config.url,
                layer=config.layer,
                version=config.version,
                format=config.format,
                bounds=config.bounds,
                attribution=config.attribution,
                style_name=config.style_name,
            ),
            style=config.style,
        )
    )


class ComposeMapConfig(NodeConfig):
    basemap: BasemapKind = "openstreetmap"
    initial_bounds: Bounds | None = None


class ComposeMapInput(NodeInput):
    layers: Annotated[
        RefSequence[GeoMapLayer],
        Field(description="Ordered map-layer artifact reference sequence."),
    ]

    @model_validator(mode="after")
    def validate_ordered_layers(self) -> Self:
        if not self.layers.ordered:
            raise ValueError("Map composition requires an ordered map-layer sequence")
        return self


class ComposeMapOutput(NodeOutput):
    map: Annotated[
        GeoMapDocument,
        Field(description="Ordered interactive map composition."),
    ]


@GIS.function_node(
    operator_id="gis.map.compose",
    version=1,
    title="Compose map",
    cache_policy=NodeCachePolicy.EXACT,
)
async def compose_map(
    config: ComposeMapConfig,
    inputs: ComposeMapInput,
) -> ComposeMapOutput:
    """Compose an ordered sequence of map layers into an interactive map."""

    return ComposeMapOutput(
        map=GeoMapDocument(
            layers=inputs.layers.item_refs,
            basemap=config.basemap,
            initial_bounds=config.initial_bounds,
        )
    )


__all__ = [
    "ComposeMapConfig",
    "ComposeMapInput",
    "ComposeMapOutput",
    "GeoJsonParseError",
    "GeoJsonParseInput",
    "GeoJsonParseOutput",
    "GeoRasterScanImportConfig",
    "GeoRasterScanImportError",
    "GeoRasterScanImportInput",
    "GeoRasterScanImportOutput",
    "GeoFeaturesToTableConfig",
    "GeoFeaturesToTableError",
    "GeoFeaturesToTableInput",
    "GeoFeaturesToTableOutput",
    "ImportRasterScanNode",
    "ImportWfsNode",
    "MapLayerOutput",
    "ParseGeoJsonNode",
    "RasterLayerConfig",
    "RasterLayerInput",
    "RasterMosaicConfig",
    "RasterMosaicInput",
    "TableToGeoFeaturesConfig",
    "TableToGeoFeaturesError",
    "TableToGeoFeaturesInput",
    "VectorLayerConfig",
    "VectorLayerInput",
    "WfsImportConfig",
    "WfsImportInput",
    "WfsImportOutput",
    "WmsLayerConfig",
    "WmsLayerInput",
    "build_raster_layer",
    "build_raster_mosaic",
    "build_vector_layer",
    "build_wms_layer",
    "compose_map",
    "geo_features_to_table",
    "table_to_geo_features",
]

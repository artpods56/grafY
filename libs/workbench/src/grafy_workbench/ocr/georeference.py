"""Place recognized TIFF text on the map through the page's own georeference."""

from math import isfinite
from typing import final, override

from pydantic import Field
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely import (
    Polygon,
    make_valid,  # pyright: ignore[reportUnknownVariableType]
)

from grafy_core.artifacts import NoConfig, NodeInput, NodeOutput
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType
from grafy_core.text_regions import PixelAffine, PixelPoint, TiffPageOpener

import grafy_workbench.table.plugin as _table_plugin
from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.tiff_recognition import TiffRecognizedText

# The table family notes Table as table.data, which the output port derives from.
_ = _table_plugin.__name__

_COLUMNS = [
    TableColumn(id="region", title="Region", value_type=TableValueType.INTEGER),
    TableColumn(id="text", title="Text", value_type=TableValueType.TEXT),
    TableColumn(id="confidence", title="Confidence", value_type=TableValueType.NUMBER),
    TableColumn(id="recognizer", title="Recognizer", value_type=TableValueType.TEXT),
    TableColumn(
        id="detection_score", title="Detection score", value_type=TableValueType.NUMBER
    ),
    TableColumn(id="pixel_col", title="Pixel column", value_type=TableValueType.NUMBER),
    TableColumn(id="pixel_row", title="Pixel row", value_type=TableValueType.NUMBER),
    TableColumn(id="longitude", title="Longitude", value_type=TableValueType.NUMBER),
    TableColumn(id="latitude", title="Latitude", value_type=TableValueType.NUMBER),
    TableColumn(
        id="point_wkt",
        title="WGS84 center (WKT)",
        value_type=TableValueType.TEXT,
    ),
    TableColumn(
        id="geometry_wkt",
        title="WGS84 geometry (WKT)",
        value_type=TableValueType.TEXT,
    ),
    TableColumn(
        id="source_artifact_id",
        title="Source TIFF",
        value_type=TableValueType.TEXT,
    ),
]


class _PageToWgs84:
    """Source-page pixel corners to WGS84 longitude and latitude."""

    def __init__(self, affine: PixelAffine, crs: str) -> None:
        self._affine = affine
        try:
            source = CRS.from_string(crs)
        except CRSError as exc:
            raise UserFacingNodeError(
                "The TIFF page has a coordinate reference system that cannot be read"
            ) from exc
        self._transformer = Transformer.from_crs(
            source, CRS.from_epsg(4326), always_xy=True
        )

    def __call__(self, col: float, row: float) -> tuple[float, float]:
        a, b, c, d, e, f = self._affine
        longitude, latitude = self._transformer.transform(
            a * col + b * row + c, d * col + e * row + f
        )
        if not (isfinite(longitude) and isfinite(latitude)):
            raise UserFacingNodeError(
                f"Pixel ({col:g}, {row:g}) has no position in WGS84"
            )
        return longitude, latitude


def _center(polygon: list[PixelPoint]) -> tuple[float, float]:
    shape = make_valid(Polygon(polygon))
    if shape.area > 0:
        return shape.centroid.x, shape.centroid.y
    # A degenerate detection still sits somewhere: use the middle of its points.
    left, top, right, bottom = Polygon(polygon).bounds
    return (left + right) / 2, (top + bottom) / 2


class GeoreferencePlacesInput(NodeInput):
    text: TiffRecognizedText = Field(
        title="Recognized text",
        description="Text read from a georeferenced TIFF page.",
    )


class GeoreferencePlacesOutput(NodeOutput):
    places: Table = Field(
        title="Places",
        description=(
            "One row per text region: what it says, its centre as WGS84 "
            "longitude and latitude, and its outline as WGS84 WKT."
        ),
    )


@OCR.node(
    operator_id="ocr.georeference_places",
    version=1,
    title="Place TIFF text on the map",
    factory=lambda context: GeoreferencePlacesNode(context.open_tiff_page),
)
@final
class GeoreferencePlacesNode(
    Node[NoConfig, GeoreferencePlacesInput, GeoreferencePlacesOutput]
):
    """Projects recognized text regions from TIFF pixels to WGS84."""

    def __init__(self, open_page: TiffPageOpener | None) -> None:
        self._open_page = open_page

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: GeoreferencePlacesInput,
        /,
    ) -> GeoreferencePlacesOutput:
        if self._open_page is None:
            raise UserFacingNodeError("TIFF window reading is unavailable")
        recognized = inputs.text
        page = await self._open_page(
            context.workspace_id,
            recognized.source.artifact_id,
            page=recognized.window.page,
        )
        if page.affine is None or page.crs is None:
            raise UserFacingNodeError(
                "This TIFF page is not georeferenced, so its text has no place "
                "on the map"
            )
        to_wgs84 = _PageToWgs84(page.affine, page.crs)
        source_artifact_id = str(recognized.source.artifact_id)

        rows: list[dict[str, TableValue]] = []
        for index, region in enumerate(recognized.regions):
            col, row = _center(region.polygon)
            longitude, latitude = to_wgs84(col, row)
            outline = Polygon([to_wgs84(x, y) for x, y in region.polygon])
            reading = region.reading
            rows.append(
                {
                    "region": index,
                    "text": region.text if reading is None else reading.text,
                    "confidence": None if reading is None else reading.confidence,
                    "recognizer": None if reading is None else reading.model,
                    "detection_score": region.score,
                    "pixel_col": col,
                    "pixel_row": row,
                    "longitude": longitude,
                    "latitude": latitude,
                    "point_wkt": f"POINT ({longitude} {latitude})",
                    "geometry_wkt": outline.wkt,
                    "source_artifact_id": source_artifact_id,
                }
            )
        return GeoreferencePlacesOutput(places=Table(columns=_COLUMNS, rows=rows))

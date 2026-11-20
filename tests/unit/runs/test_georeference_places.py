import math
from collections.abc import Awaitable, Callable, Sequence
from typing import cast
from uuid import UUID, uuid4

import pytest
from pyproj import CRS
from shapely import Polygon, wkt

from grafy_core.artifacts import NoConfig
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.node_ports import Ref
from grafy_core.text_regions import PixelAffine, TextReading, TiffPage
from grafy_plugin_gis.nodes import (
    TableToGeoFeaturesConfig,
    TableToGeoFeaturesInput,
    TableToGeoFeaturesOutput,
    table_to_geo_features,
)
from grafy_workbench.ocr.georeference import (
    GeoreferencePlacesInput,
    GeoreferencePlacesNode,
)
from grafy_workbench.ocr.text_regions import TiffPixelWindow
from grafy_workbench.ocr.tiff_recognition import (
    TiffRecognizedRegion,
    TiffRecognizedText,
)

# Web Mercator metres for one degree of longitude and of latitude at the equator.
_DEGREE_X = 111319.49079327357
_DEGREE_Y = 111325.1428663851
# 100 pixels span one degree each way, and the top-left corner sits at (0°, 1°N).
_MERCATOR: PixelAffine = (_DEGREE_X / 100, 0, 0, 0, -_DEGREE_Y / 100, _DEGREE_Y)
# The node decorator types the function as either of its two call shapes.
_to_features = cast(
    Callable[
        [TableToGeoFeaturesConfig, TableToGeoFeaturesInput],
        Awaitable[TableToGeoFeaturesOutput],
    ],
    table_to_geo_features,
)


async def _never_read(*, col: int, row: int, width: int, height: int) -> bytes:
    raise AssertionError("georeferencing reads no pixels")


def _opener(
    affine: PixelAffine | None, crs: str | None, opened: list[tuple[UUID, int]]
):
    async def open_page(workspace_id: UUID, artifact_id: UUID, *, page: int):
        del workspace_id
        opened.append((artifact_id, page))
        return TiffPage(
            200,
            200,
            _never_read,
            source_sha256="e" * 64,
            page=page,
            affine=affine,
            crs=crs,
        )

    return open_page


def _recognized(artifact_id: UUID) -> TiffRecognizedText:
    return TiffRecognizedText(
        source=Ref[TiffFile](
            artifact_id=artifact_id, artifact_type="file.tiff", schema_version=1
        ),
        window=TiffPixelWindow(page=3, col=0, row=0, width=200, height=200),
        regions=[
            TiffRecognizedRegion(
                polygon=[(90, 90), (110, 90), (110, 110), (90, 110)],
                score=0.7,
                reading=TextReading(text="Бѣлыничи", confidence=0.81, model="paddle"),
            ),
            TiffRecognizedRegion(
                polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
                text="detector text",
                reading=None,
            ),
        ],
    )


def _close(actual: Sequence[float], expected: Sequence[float]) -> bool:
    return all(
        math.isclose(a, e, abs_tol=1e-9) for a, e in zip(actual, expected, strict=True)
    )


async def test_projects_region_centres_and_outlines_to_wgs84() -> None:
    artifact_id = uuid4()
    opened: list[tuple[UUID, int]] = []
    node = GeoreferencePlacesNode(
        _opener(_MERCATOR, CRS.from_epsg(3857).to_wkt(), opened)
    )

    result = await node.run(
        NodeExecutionContext(workspace_id=uuid4()),
        NoConfig(),
        GeoreferencePlacesInput(text=_recognized(artifact_id)),
    )

    assert opened == [(artifact_id, 3)]
    table = result.places
    assert [column.id for column in table.columns] == [
        "region",
        "text",
        "confidence",
        "recognizer",
        "detection_score",
        "pixel_col",
        "pixel_row",
        "longitude",
        "latitude",
        "geometry_wkt",
    ]
    label, square = table.rows
    assert {key: label[key] for key in ("region", "text", "confidence")} == {
        "region": 0,
        "text": "Бѣлыничи",
        "confidence": 0.81,
    }
    assert (label["recognizer"], label["detection_score"]) == ("paddle", 0.7)
    assert (label["pixel_col"], label["pixel_row"]) == (100.0, 100.0)
    longitude, latitude = label["longitude"], label["latitude"]
    assert isinstance(longitude, float) and isinstance(latitude, float)
    assert _close((longitude, latitude), (1.0, 0.0))

    assert (square["text"], square["confidence"], square["recognizer"]) == (
        "detector text",
        None,
        None,
    )
    outline = square["geometry_wkt"]
    assert isinstance(outline, str)
    polygon = wkt.loads(outline)
    assert isinstance(polygon, Polygon)
    corners = list(polygon.exterior.coords)
    expected = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)]
    assert all(_close(actual, want) for actual, want in zip(corners, expected))


async def test_places_flow_on_into_geo_features() -> None:
    node = GeoreferencePlacesNode(_opener(_MERCATOR, CRS.from_epsg(3857).to_wkt(), []))
    places = await node.run(
        NodeExecutionContext(workspace_id=uuid4()),
        NoConfig(),
        GeoreferencePlacesInput(text=_recognized(uuid4())),
    )

    features = await _to_features(
        TableToGeoFeaturesConfig(
            geometry_column="WGS84 geometry (WKT)", source_crs="EPSG:4326"
        ),
        TableToGeoFeaturesInput(table=places.places),
    )

    label = features.features.features[0]
    properties = label["properties"]
    assert isinstance(properties, dict)
    assert properties["text"] == "Бѣлыничи"
    geometry = label["geometry"]
    assert isinstance(geometry, dict)
    assert geometry["type"] == "Polygon"
    assert features.features.bounds is not None
    assert all(
        math.isclose(actual, expected, abs_tol=1e-4)
        for actual, expected in zip(features.features.bounds, (0.0, -0.1, 1.1, 1.0))
    )


async def test_a_page_without_georeference_is_refused() -> None:
    node = GeoreferencePlacesNode(_opener(None, None, []))

    with pytest.raises(UserFacingNodeError, match="not georeferenced"):
        await node.run(
            NodeExecutionContext(workspace_id=uuid4()),
            NoConfig(),
            GeoreferencePlacesInput(text=_recognized(uuid4())),
        )


async def test_an_unreadable_crs_is_refused() -> None:
    node = GeoreferencePlacesNode(_opener(_MERCATOR, "not a CRS", []))

    with pytest.raises(UserFacingNodeError, match="cannot be read"):
        await node.run(
            NodeExecutionContext(workspace_id=uuid4()),
            NoConfig(),
            GeoreferencePlacesInput(text=_recognized(uuid4())),
        )


async def test_without_tiff_reading_the_node_says_so() -> None:
    with pytest.raises(UserFacingNodeError, match="unavailable"):
        await GeoreferencePlacesNode(None).run(
            NodeExecutionContext(workspace_id=uuid4()),
            NoConfig(),
            GeoreferencePlacesInput(text=_recognized(uuid4())),
        )


def test_a_page_carries_affine_and_crs_together() -> None:
    with pytest.raises(ValueError, match="together"):
        TiffPage(1, 1, _never_read, source_sha256="e" * 64, page=0, affine=_MERCATOR)

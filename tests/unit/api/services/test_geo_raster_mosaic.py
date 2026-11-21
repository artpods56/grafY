import json
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from grafy_core.artifacts import ArtifactObject, JsonObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.spatial_contracts import GeoRasterStyle
from grafy_shared.config.tiler import TilerConfig
from grafy_storage import LocalFileObjectStore
from pydantic import HttpUrl, SecretStr

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.artifacts.errors import GeoRasterUnavailableError
from grafy_api.artifacts.geo import ArtifactGeoService
from grafy_api.artifacts.geo_tiff import bounds_intersect_tile, fit_min_zoom
from grafy_api.artifacts.geo_tiles import ArtifactGeoTileService
from grafy_api.artifacts.images import (
    ImageProxyError,
    TiffSource,
    TileExtension,
    TilerImage,
    TilerPort,
    TilerWindow,
)
from grafy_api.artifacts.models import ImageInfoResponse
from grafy_api.artifacts.wms import WmsTileClient
from grafy_api.services.errors import ArtifactContentUnavailableError

WS = UUID(int=7)
OTHER_WS = UUID(int=8)

# z=2 tile (2, 1) covers longitudes 0..90, tile (3, 1) covers 90..180.
SHEET_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "west.tif": (10.0, 10.0, 20.0, 20.0),
    "east.tif": (100.0, 10.0, 110.0, 20.0),
    "overlap.tif": (15.0, 10.0, 30.0, 20.0),
}


class RecordingTiler(TilerPort):
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.single: list[TiffSource] = []
        self.mosaics: list[list[TiffSource]] = []
        self.mosaic_status: int | None = None

    async def info(self, source: TiffSource) -> ImageInfoResponse:
        self.infos.append(source.key)
        return ImageInfoResponse(
            width=1024,
            height=1024,
            page_count=1,
            has_alpha=True,
            tile_size=256,
            min_level=0,
            max_level=10,
            tile_format="png",
            georeferenced=True,
            bounds_wgs84=SHEET_BOUNDS[source.key],
        )

    async def tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage:
        raise AssertionError("image-space tiles are not used by maps")

    async def geo_tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage:
        self.single.append(source)
        return TilerImage(b"single", "image/png")

    async def geo_mosaic_tile(
        self,
        sources: Sequence[TiffSource],
        *,
        z: int,
        x: int,
        y: int,
        extension: TileExtension,
    ) -> TilerImage:
        self.mosaics.append(list(sources))
        if self.mosaic_status is not None:
            raise ImageProxyError(self.mosaic_status, "Tiler could not render")
        return TilerImage(b"mosaic", "image/png")

    async def thumbnail(self, source: TiffSource, *, edge: int) -> TilerImage:
        raise AssertionError("thumbnails are not used by maps")

    async def read_window(
        self, source: TiffSource, *, col: int, row: int, width: int, height: int
    ) -> TilerWindow:
        raise AssertionError("windows are not used by maps")

    async def close(self) -> None:
        return None


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.uow = InMemoryUnitOfWork()
        self.tiler = RecordingTiler()
        storage = LocalFileObjectStore(tmp_path / "objects")
        availability = ArtifactAvailability(self.uow)
        config = TilerConfig.model_construct(
            tiler_url=HttpUrl("http://tiler"),
            tiler_shared_key=SecretStr("k" * 64),
        )
        self.geo = ArtifactGeoService(
            self.uow,
            storage,
            availability=availability,
            tiler=self.tiler,
            tiler_config=config,
        )
        self.tiles = ArtifactGeoTileService(
            self.uow,
            storage,
            availability=availability,
            wms=WmsTileClient(),
            tiler=self.tiler,
            tiler_config=config,
        )

    async def add(self, artifact: ArtifactObject) -> ArtifactObject:
        async with self.uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact

    async def tiff(self, key: str, *, workspace_id: UUID = WS) -> ArtifactObject:
        return await self.add(
            ArtifactObject(
                workspace_id=workspace_id,
                artifact_type="file.tiff",
                schema_version=1,
                content_type="image/tiff",
                bucket="test",
                object_key=key,
                byte_size=4,
                sha256=sha256(key.encode()).hexdigest(),
                metadata={"original_filename": key},
            )
        )

    async def raster_scan(self, *, prefix: str | None = None) -> ArtifactObject:
        return await self.add(
            ArtifactObject(
                workspace_id=WS,
                artifact_type="geo.raster_scan",
                schema_version=1,
                content_type="image/tiff; application=geotiff",
                bucket="test",
                object_key="scan.cog.tif",
                byte_size=8,
                sha256="c" * 64,
                metadata={
                    "source_name": "Scan",
                    "raster_projection": {
                        "kind": "xyz",
                        "bucket": "test",
                        "prefix": prefix,
                        "extension": "png",
                        "content_type": "image/png",
                        "min_zoom": 1,
                        "max_zoom": 9,
                        "tile_size": 256,
                        "bounds": [40.0, 10.0, 50.0, 20.0],
                        "source_crs": "EPSG:3857",
                        "width": 1024,
                        "height": 1024,
                        "band_count": 3,
                        "compiler": "fixture",
                    },
                },
            )
        )

    async def mosaic(
        self, sources: list[ArtifactObject], **layer: object
    ) -> ArtifactObject:
        payload: JsonObject = {
            "title": "Sheets",
            "visible": True,
            "opacity": 1.0,
            "min_zoom": 0,
            "max_zoom": 22,
            "source": {
                "kind": "raster_mosaic",
                "artifacts": [
                    source.ref().model_dump(mode="json") for source in sources
                ],
            },
            "style": GeoRasterStyle().model_dump(mode="json"),
            **layer,  # pyright: ignore[reportAssignmentType]
        }
        content = json.dumps(payload, sort_keys=True).encode()
        return await self.add(
            ArtifactObject(
                workspace_id=WS,
                artifact_type="geo.map_layer",
                schema_version=1,
                content_type="application/json",
                storage_backend="inline",
                inline_payload=payload,
                byte_size=len(content),
                sha256=sha256(content).hexdigest(),
            )
        )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


async def test_render_descriptor_points_at_the_layer_and_unions_bounds(
    harness: Harness,
) -> None:
    west = await harness.tiff("west.tif")
    east = await harness.tiff("east.tif")
    scan = await harness.raster_scan()
    layer = await harness.mosaic([west, scan, east])

    descriptor = await harness.geo.load_geo_render(layer, workspace_id=WS)

    assert descriptor.kind == "map_layer"
    assert descriptor.initial_bounds == (10.0, 10.0, 110.0, 20.0)
    [rendered] = descriptor.layers
    assert rendered.source.kind == "raster"
    assert rendered.source.artifact_id == layer.id
    assert rendered.source.tilejson_url == (
        f"/v1/workspaces/{WS}/artifacts/{layer.id}/geo/raster/tilejson.json"
    )
    # The raster scan's footprint comes from its metadata, not from the tiler.
    assert sorted(harness.tiler.infos) == ["east.tif", "west.tif"]


async def test_tilejson_fits_the_union_and_respects_layer_zooms(
    harness: Harness,
) -> None:
    west = await harness.tiff("west.tif")
    east = await harness.tiff("east.tif")
    wide = await harness.mosaic([west, east])
    clamped = await harness.mosaic([west, east], min_zoom=5, max_zoom=6)

    tilejson = await harness.tiles.load_raster_tilejson(wide, workspace_id=WS)
    narrowed = await harness.tiles.load_raster_tilejson(clamped, workspace_id=WS)

    union = (10.0, 10.0, 110.0, 20.0)
    assert tilejson.bounds == union
    assert tilejson.minzoom == fit_min_zoom(union) == 0
    assert tilejson.maxzoom == 8
    assert tilejson.tiles == [
        f"/v1/workspaces/{WS}/artifacts/{wide.id}/geo/raster/{{z}}/{{x}}/{{y}}.png"
    ]
    assert (narrowed.minzoom, narrowed.maxzoom) == (5, 6)
    # Each sheet's info is fetched once and then remembered.
    assert sorted(harness.tiler.infos) == ["east.tif", "west.tif"]


async def test_tiles_send_only_the_overlapping_sheets_bottom_to_top(
    harness: Harness,
) -> None:
    west = await harness.tiff("west.tif")
    east = await harness.tiff("east.tif")
    overlap = await harness.tiff("overlap.tif")
    layer = await harness.mosaic([west, east, overlap])

    stacked = await harness.tiles.load_raster_tile(
        layer, workspace_id=WS, z=2, x=2, y=1
    )
    alone = await harness.tiles.load_raster_tile(layer, workspace_id=WS, z=2, x=3, y=1)
    empty = await harness.tiles.load_raster_tile(layer, workspace_id=WS, z=2, x=0, y=0)
    off_grid = await harness.tiles.load_raster_tile(
        layer, workspace_id=WS, z=2, x=4, y=0
    )

    assert stacked is not None and stacked.content == b"mosaic"
    assert stacked.etag == f'"{sha256(b"mosaic").hexdigest()}"'
    assert [
        [source.key for source in sources] for sources in harness.tiler.mosaics
    ] == [["west.tif", "overlap.tif"]]
    assert alone is not None and alone.content == b"single"
    assert [source.key for source in harness.tiler.single] == ["east.tif"]
    assert empty is None
    assert off_grid is None


async def test_a_mosaic_tile_the_tiler_cannot_find_is_empty(
    harness: Harness,
) -> None:
    layer = await harness.mosaic(
        [await harness.tiff("west.tif"), await harness.tiff("overlap.tif")]
    )
    harness.tiler.mosaic_status = 404
    assert (
        await harness.tiles.load_raster_tile(layer, workspace_id=WS, z=2, x=2, y=1)
        is None
    )
    harness.tiler.mosaic_status = 503
    with pytest.raises(ImageProxyError):
        await harness.tiles.load_raster_tile(layer, workspace_id=WS, z=2, x=2, y=1)


async def test_mosaic_cannot_reach_into_another_workspace(harness: Harness) -> None:
    foreign = await harness.tiff("west.tif", workspace_id=OTHER_WS)
    layer = await harness.mosaic([await harness.tiff("east.tif"), foreign])

    with pytest.raises(ArtifactContentUnavailableError):
        await harness.geo.load_geo_render(layer, workspace_id=WS)
    with pytest.raises(ArtifactContentUnavailableError):
        await harness.tiles.load_raster_tilejson(layer, workspace_id=WS)
    with pytest.raises(ArtifactContentUnavailableError):
        await harness.tiles.load_raster_tile(layer, workspace_id=WS, z=2, x=2, y=1)
    assert harness.tiler.mosaics == harness.tiler.single == []


async def test_a_static_tile_pyramid_cannot_join_a_mosaic(harness: Harness) -> None:
    layer = await harness.mosaic(
        [await harness.tiff("west.tif"), await harness.raster_scan(prefix="xyz")]
    )
    with pytest.raises(GeoRasterUnavailableError, match="static tile pyramid"):
        await harness.tiles.load_raster_tilejson(layer, workspace_id=WS)


@pytest.mark.parametrize(
    ("bounds", "tile", "expected"),
    [
        ((10.0, 10.0, 20.0, 20.0), (2, 2, 1), True),
        ((10.0, 10.0, 20.0, 20.0), (2, 3, 1), False),
        ((10.0, -20.0, 20.0, -10.0), (2, 2, 1), False),
        # Crossing the antimeridian touches both edges of the world.
        ((170.0, 10.0, -170.0, 20.0), (2, 3, 1), True),
        ((170.0, 10.0, -170.0, 20.0), (2, 0, 1), True),
        ((170.0, 10.0, -170.0, 20.0), (2, 2, 1), False),
    ],
)
def test_bounds_intersect_tile(
    bounds: tuple[float, float, float, float],
    tile: tuple[int, int, int],
    expected: bool,
) -> None:
    z, x, y = tile
    assert bounds_intersect_tile(bounds, z=z, x=x, y=y) is expected

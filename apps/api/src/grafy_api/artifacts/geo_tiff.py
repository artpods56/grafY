import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Final
from weakref import WeakKeyDictionary

from grafy_core.artifacts import ArtifactObject
from grafy_core.spatial_bounds import GeoBounds
from grafy_shared.config.tiler import TilerConfig

from grafy_api.artifacts.errors import GeoRasterUnavailableError
from grafy_api.artifacts.images import TiffSource, TilerPort, stored_tiff_source

TIFF_ARTIFACT_TYPE = "file.tiff"
_INFO_CACHE_ENTRIES: Final = 512


@dataclass(frozen=True, slots=True)
class GeoTiffInfo:
    source: TiffSource
    bounds: GeoBounds
    min_zoom: int
    max_zoom: int


# Successful tiler answers only, keyed by the digest-addressed source. A
# mosaic asks for every sheet's footprint on every tile, so this saves one
# tiler round trip per sheet per tile. Each tiler has its own entries, so two
# tilers (or two test fakes) never share an answer.
type _InfoKey = tuple[str, str, str, int, int]
_infos: WeakKeyDictionary[TilerPort, OrderedDict[_InfoKey, GeoTiffInfo]] = (
    WeakKeyDictionary()
)


def require_raster_tiler(
    tiler: TilerPort | None, config: TilerConfig | None
) -> TilerPort:
    if tiler is None or config is None or config.tiler_url is None:
        raise GeoRasterUnavailableError("GeoTIFF rendering requires a configured tiler")
    return tiler


def tiff_title(artifact: ArtifactObject) -> str:
    filename = artifact.metadata.get("original_filename")
    return filename if isinstance(filename, str) and filename.strip() else "GeoTIFF"


def _mercator_y(latitude: float) -> float:
    clamped = max(-85.05112878, min(85.05112878, latitude))
    return math.asinh(math.tan(math.radians(clamped))) / math.tau


def tile_bounds_wgs84(z: int, x: int, y: int) -> GeoBounds:
    """West, south, east, north of one XYZ Web Mercator tile."""
    scale = 1 << z
    west = x / scale * 360.0 - 180.0
    east = (x + 1) / scale * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / scale))))
    return (west, south, east, north)


def bounds_intersect_tile(bounds: GeoBounds, *, z: int, x: int, y: int) -> bool:
    """Whether WGS84 bounds overlap a tile; bounds crossing 180° count both sides."""
    tile_west, tile_south, tile_east, tile_north = tile_bounds_wgs84(z, x, y)
    west, south, east, north = bounds
    if south >= tile_north or north <= tile_south:
        return False
    if west > east:
        return east > tile_west or west < tile_east
    return west < tile_east and east > tile_west


def fit_min_zoom(bounds: GeoBounds) -> int:
    """Two levels below the zoom at which the footprint fills one tile."""
    west, south, east, north = bounds
    longitude_span = east - west
    if longitude_span < 0:
        longitude_span += 360
    span_x = longitude_span / 360
    span_y = _mercator_y(north) - _mercator_y(south)
    return max(0, math.floor(-math.log2(max(span_x, span_y, 2.0**-22))) - 2)


async def load_geo_tiff(artifact: ArtifactObject, tiler: TilerPort) -> GeoTiffInfo:
    """Footprint and zoom range of one file.tiff@1 read by the tiler."""
    source = stored_tiff_source(artifact, page=0)
    known_infos = _infos.setdefault(tiler, OrderedDict())
    key: _InfoKey = (
        source.bucket,
        source.key,
        source.sha256,
        source.byte_size,
        source.page,
    )
    known = known_infos.get(key)
    if known is not None:
        known_infos.move_to_end(key)
        return known
    info = await tiler.info(source)
    bounds = info.bounds_wgs84
    if not info.georeferenced or bounds is None:
        raise GeoRasterUnavailableError(
            f"TIFF artifact {artifact.id} is not georeferenced"
        )
    west, south, east, north = bounds
    longitude_span = east - west
    if longitude_span < 0:
        longitude_span += 360
    span_x = longitude_span / 360
    span_y = _mercator_y(north) - _mercator_y(south)
    # Start two levels below the footprint zoom so the map can fit padding.
    # Stop at native resolution on the coarser axis of a 256px XYZ tile.
    native_zoom = -math.log2(
        max(256 * span_x / info.width, 256 * span_y / info.height, 2.0**-22)
    )
    min_zoom = fit_min_zoom(bounds)
    max_zoom = max(min_zoom, min(22, math.ceil(native_zoom)))
    loaded = GeoTiffInfo(source, bounds, min_zoom, max_zoom)
    known_infos[key] = loaded
    while len(known_infos) > _INFO_CACHE_ENTRIES:
        _ = known_infos.popitem(last=False)
    return loaded

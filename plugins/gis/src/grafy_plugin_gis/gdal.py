import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final, Literal, final

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError


RasterBounds = tuple[float, float, float, float]

MINIMUM_GDAL_VERSION: Final = (3, 8, 0)
PMTILES_MAX_ZOOM: Final = 22
COG_BLOCK_SIZE: Final = 256


class GdalError(RuntimeError):
    """A GDAL capability, input-validation, or compilation failure."""


class GdalCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gdalinfo_version: StrictStr
    ogr2ogr_version: StrictStr
    gdal_translate_version: StrictStr
    gdal2tiles_version: StrictStr
    pmtiles_write: bool
    cog_write: bool
    png_write: bool


class VectorTileCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    destination: Path
    driver: Literal["PMTiles"] = "PMTiles"
    compiler: Literal["ogr2ogr"] = "ogr2ogr"
    compiler_version: StrictStr
    source_layer: StrictStr = Field(min_length=1)
    source_crs: Literal["EPSG:4326"] = "EPSG:4326"
    tile_crs: Literal["EPSG:3857"] = "EPSG:3857"
    min_zoom: StrictInt = Field(ge=0, le=PMTILES_MAX_ZOOM)
    max_zoom: StrictInt = Field(ge=0, le=PMTILES_MAX_ZOOM)


class RasterCogCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    destination: Path
    driver: Literal["COG"] = "COG"
    compiler: Literal["gdal_translate"] = "gdal_translate"
    compiler_version: StrictStr
    native_crs: StrictStr | None
    bounds_wgs84: RasterBounds | None
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    bands: StrictInt = Field(gt=0)
    tile_size: Literal[256] = COG_BLOCK_SIZE


class RasterTileCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compiler: Literal["gdal2tiles.py"] = "gdal2tiles.py"
    compiler_version: StrictStr
    profile: Literal["mercator"] = "mercator"
    convention: Literal["xyz"] = "xyz"
    tile_crs: Literal["EPSG:3857"] = "EPSG:3857"
    tile_format: Literal["PNG"] = "PNG"
    tile_size: Literal[256] = COG_BLOCK_SIZE
    min_zoom: StrictInt | None = Field(ge=0)
    max_zoom: StrictInt | None = Field(ge=0)
    tile_count: StrictInt = Field(ge=0)


class _GdalCoordinateSystem(BaseModel):
    model_config = ConfigDict(extra="allow")

    wkt: StrictStr | None = None


class _GdalCornerCoordinates(BaseModel):
    model_config = ConfigDict(extra="allow")

    upper_left: tuple[float, float] | None = Field(default=None, alias="upperLeft")
    lower_left: tuple[float, float] | None = Field(default=None, alias="lowerLeft")
    lower_right: tuple[float, float] | None = Field(default=None, alias="lowerRight")
    upper_right: tuple[float, float] | None = Field(default=None, alias="upperRight")


class _GdalWgs84Extent(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]


class _GdalInfoBand(BaseModel):
    model_config = ConfigDict(extra="allow")

    band: StrictInt = Field(gt=0)
    block: tuple[StrictInt, StrictInt]
    overviews: list[dict[str, object]] = Field(default_factory=list)


class _GdalInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    driver_short_name: StrictStr = Field(alias="driverShortName")
    size: tuple[StrictInt, StrictInt]
    coordinate_system: _GdalCoordinateSystem | None = Field(
        default=None,
        alias="coordinateSystem",
    )
    geo_transform: tuple[float, float, float, float, float, float] | None = Field(
        default=None,
        alias="geoTransform",
    )
    corner_coordinates: _GdalCornerCoordinates | None = Field(
        default=None,
        alias="cornerCoordinates",
    )
    wgs84_extent: _GdalWgs84Extent | None = Field(
        default=None,
        alias="wgs84Extent",
    )
    bands: list[_GdalInfoBand]
    metadata: dict[str, dict[str, object]] = Field(default_factory=dict)
    stac: dict[str, object] = Field(default_factory=dict)


@final
class GdalCli:
    """Concrete CLI adapter for the GDAL formats used by spatial artifacts."""

    def __init__(
        self,
        *,
        gdalinfo: str = "gdalinfo",
        ogr2ogr: str = "ogr2ogr",
        gdal_translate: str = "gdal_translate",
        gdal2tiles: str = "gdal2tiles.py",
    ) -> None:
        self._gdalinfo = gdalinfo
        self._ogr2ogr = ogr2ogr
        self._gdal_translate = gdal_translate
        self._gdal2tiles = gdal2tiles
        self._versions: dict[str, str] = {}
        self._driver_support: dict[tuple[str, str, str], bool] = {}

    def capabilities(self) -> GdalCapabilities:
        """Inspect the required executables and their writable output drivers."""
        return GdalCapabilities(
            gdalinfo_version=self._version_for(
                self._gdalinfo,
                operation="checking gdalinfo version",
            ),
            ogr2ogr_version=self._version_for(
                self._ogr2ogr,
                operation="checking ogr2ogr version",
            ),
            gdal_translate_version=self._version_for(
                self._gdal_translate,
                operation="checking gdal_translate version",
            ),
            gdal2tiles_version=self._version_for(
                self._gdal2tiles,
                operation="checking gdal2tiles.py version",
            ),
            pmtiles_write=self._supports_writable_driver(
                self._ogr2ogr,
                driver="PMTiles",
                kind="vector",
            ),
            cog_write=self._supports_writable_driver(
                self._gdal_translate,
                driver="COG",
                kind="raster",
            ),
            png_write=self._supports_writable_driver(
                self._gdal_translate,
                driver="PNG",
                kind="raster",
            ),
        )

    def compile_geojson_to_pmtiles(
        self,
        source: Path,
        destination: Path,
        *,
        source_layer: str,
        min_zoom: int,
        max_zoom: int,
    ) -> VectorTileCompilation:
        """Compile one WGS84 GeoJSON dataset into a deterministic PMTiles file."""
        self._validate_paths(
            source,
            destination,
            operation="PMTiles compilation",
        )
        if source_layer == "":
            raise GdalError("PMTiles source layer must be a non-empty string")
        if source_layer != source_layer.strip():
            raise GdalError(
                f"PMTiles source layer {source_layer!r} must not contain surrounding whitespace"
            )
        if isinstance(min_zoom, bool) or not 0 <= min_zoom <= PMTILES_MAX_ZOOM:
            raise GdalError(
                f"PMTiles minimum zoom must be an integer from 0 to {PMTILES_MAX_ZOOM}, "
                f"got {min_zoom!r}"
            )
        if isinstance(max_zoom, bool) or not 0 <= max_zoom <= PMTILES_MAX_ZOOM:
            raise GdalError(
                f"PMTiles maximum zoom must be an integer from 0 to {PMTILES_MAX_ZOOM}, "
                f"got {max_zoom!r}"
            )
        if min_zoom > max_zoom:
            raise GdalError(
                f"PMTiles minimum zoom {min_zoom} cannot exceed maximum zoom {max_zoom}"
            )

        compiler_version = self._version_for(
            self._ogr2ogr,
            operation=f"checking ogr2ogr before compiling {source}",
        )
        if not self._supports_writable_driver(
            self._ogr2ogr,
            driver="PMTiles",
            kind="vector",
        ):
            raise GdalError(
                f"GDAL {compiler_version} executable {self._ogr2ogr!r} does not "
                "provide a writable PMTiles vector driver"
            )

        try:
            self._run(
                self._ogr2ogr,
                [
                    "--config",
                    "GDAL_NUM_THREADS",
                    "1",
                    "-f",
                    "PMTiles",
                    "-if",
                    "GeoJSON",
                    "-s_srs",
                    "EPSG:4326",
                    "-t_srs",
                    "EPSG:3857",
                    "-dim",
                    "XY",
                    "-nln",
                    source_layer,
                    "-dsco",
                    f"NAME={source_layer}",
                    "-dsco",
                    f"MINZOOM={min_zoom}",
                    "-dsco",
                    f"MAXZOOM={max_zoom}",
                    str(destination),
                    str(source),
                ],
                operation=(
                    f"compiling GeoJSON {source} to PMTiles {destination} "
                    f"for layer {source_layer!r} at zooms {min_zoom}-{max_zoom}"
                ),
            )
            self._validate_created_file(
                destination,
                operation=f"PMTiles compilation from {source}",
            )
        except GdalError:
            self._remove_partial_output(destination)
            raise

        return VectorTileCompilation(
            destination=destination,
            compiler_version=compiler_version,
            source_layer=source_layer,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
        )

    def normalize_geotiff_to_cog(
        self,
        source: Path,
        destination: Path,
    ) -> RasterCogCompilation:
        """Validate an uploaded GeoTIFF and normalize it to a 256px-tiled COG."""
        self._validate_paths(
            source,
            destination,
            operation="GeoTIFF normalization",
        )
        self._version_for(
            self._gdalinfo,
            operation=f"checking gdalinfo before validating {source}",
        )
        compiler_version = self._version_for(
            self._gdal_translate,
            operation=f"checking gdal_translate before normalizing {source}",
        )
        if not self._supports_writable_driver(
            self._gdal_translate,
            driver="COG",
            kind="raster",
        ):
            raise GdalError(
                f"GDAL {compiler_version} executable {self._gdal_translate!r} does "
                "not provide a writable COG raster driver"
            )

        source_info = self._inspect_geotiff(
            source,
            operation=f"validating uploaded GeoTIFF {source}",
        )
        try:
            self._run(
                self._gdal_translate,
                [
                    "-if",
                    "GTiff",
                    "-of",
                    "COG",
                    "-co",
                    f"BLOCKSIZE={COG_BLOCK_SIZE}",
                    "-co",
                    "COMPRESS=DEFLATE",
                    "-co",
                    "BIGTIFF=IF_SAFER",
                    "-co",
                    "OVERVIEWS=AUTO",
                    str(source),
                    str(destination),
                ],
                operation=f"normalizing GeoTIFF {source} to COG {destination}",
            )
            self._validate_created_file(
                destination,
                operation=f"COG normalization from {source}",
            )
            output_info = self._inspect_geotiff(
                destination,
                operation=f"validating normalized COG {destination}",
                include_image_structure=True,
            )
            self._validate_cog_output(
                source_info=source_info,
                output_info=output_info,
                source=source,
                destination=destination,
            )
        except GdalError:
            self._remove_partial_output(destination)
            raise

        return RasterCogCompilation(
            destination=destination,
            compiler_version=compiler_version,
            native_crs=self._native_crs(output_info),
            bounds_wgs84=self._wgs84_bounds(output_info),
            width=output_info.size[0],
            height=output_info.size[1],
            bands=len(output_info.bands),
        )

    def tile_raster_to_xyz(
        self,
        cog_source: Path,
        destination_dir: Path,
        *,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
    ) -> RasterTileCompilation:
        """Render a canonical COG into a browser-ready XYZ PNG directory."""
        self._validate_directory_paths(
            cog_source,
            destination_dir,
            operation="XYZ raster tiling",
        )
        if min_zoom is not None and (isinstance(min_zoom, bool) or min_zoom < 0):
            raise GdalError(
                f"XYZ minimum zoom must be a non-negative integer or None, got {min_zoom!r}"
            )
        if max_zoom is not None and (isinstance(max_zoom, bool) or max_zoom < 0):
            raise GdalError(
                f"XYZ maximum zoom must be a non-negative integer or None, got {max_zoom!r}"
            )
        if min_zoom is not None and max_zoom is not None and min_zoom > max_zoom:
            raise GdalError(
                f"XYZ minimum zoom {min_zoom} cannot exceed maximum zoom {max_zoom}"
            )

        self._version_for(
            self._gdalinfo,
            operation=f"checking gdalinfo before tiling {cog_source}",
        )
        compiler_version = self._version_for(
            self._gdal2tiles,
            operation=f"checking gdal2tiles.py before tiling {cog_source}",
        )
        gdal_translate_version = self._version_for(
            self._gdal_translate,
            operation=f"checking PNG driver before tiling {cog_source}",
        )
        if not self._supports_writable_driver(
            self._gdal_translate,
            driver="PNG",
            kind="raster",
        ):
            raise GdalError(
                f"GDAL {gdal_translate_version} executable {self._gdal_translate!r} "
                "does not provide a writable PNG raster driver"
            )

        source_info = self._inspect_geotiff(
            cog_source,
            operation=f"validating COG source {cog_source} before XYZ tiling",
            include_image_structure=True,
        )
        image_structure = source_info.metadata.get("IMAGE_STRUCTURE", {})
        if image_structure.get("LAYOUT") != "COG":
            raise GdalError(
                f"XYZ raster tiling source {cog_source} does not report "
                "IMAGE_STRUCTURE LAYOUT=COG"
            )

        arguments = [
            "--profile",
            "mercator",
            "--xyz",
            "--exclude",
            "--webviewer",
            "none",
            "--processes",
            "1",
            "--tiledriver",
            "PNG",
        ]
        if min_zoom is not None or max_zoom is not None:
            if min_zoom is None:
                zoom = f"0-{max_zoom}"
            elif max_zoom is None:
                zoom = f"{min_zoom}-"
            elif min_zoom == max_zoom:
                zoom = str(min_zoom)
            else:
                zoom = f"{min_zoom}-{max_zoom}"
            arguments.extend(["--zoom", zoom])
        arguments.extend([str(cog_source), str(destination_dir)])

        try:
            self._run(
                self._gdal2tiles,
                arguments,
                operation=f"tiling COG {cog_source} into XYZ PNGs at {destination_dir}",
            )
            if not destination_dir.is_dir():
                raise GdalError(
                    f"XYZ raster tiling did not create output directory {destination_dir}"
                )
            zoom_levels = sorted(
                int(path.name)
                for path in destination_dir.iterdir()
                if path.is_dir() and path.name.isascii() and path.name.isdigit()
            )
            tile_count = 0
            for tile_path in destination_dir.rglob("*.png"):
                if not tile_path.is_file():
                    continue
                relative = tile_path.relative_to(destination_dir)
                if (
                    len(relative.parts) != 3
                    or not relative.parts[0].isascii()
                    or not relative.parts[0].isdigit()
                    or not relative.parts[1].isascii()
                    or not relative.parts[1].isdigit()
                    or not relative.stem.isascii()
                    or not relative.stem.isdigit()
                ):
                    raise GdalError(
                        f"gdal2tiles.py created non-XYZ PNG path {relative} in "
                        f"{destination_dir}"
                    )
                tile_count += 1
        except (GdalError, OSError) as exc:
            self._remove_partial_directory(destination_dir)
            if isinstance(exc, GdalError):
                raise
            raise GdalError(
                f"Failed to inspect XYZ PNG output directory {destination_dir}: {exc}"
            ) from exc

        return RasterTileCompilation(
            compiler_version=compiler_version,
            min_zoom=zoom_levels[0] if zoom_levels else None,
            max_zoom=zoom_levels[-1] if zoom_levels else None,
            tile_count=tile_count,
        )

    def _version_for(self, executable: str, *, operation: str) -> str:
        cached = self._versions.get(executable)
        if cached is not None:
            return cached

        result = self._run(executable, ["--version"], operation=operation)
        match = re.search(
            r"\bGDAL\s+(\d+)\.(\d+)(?:\.(\d+))?",
            result.stdout,
        )
        if match is None:
            raise GdalError(
                f"{operation} returned an unrecognized GDAL version: "
                f"{self._diagnostic(result.stdout)}"
            )
        version_parts = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3) or 0),
        )
        version = ".".join(str(part) for part in version_parts)
        if version_parts < MINIMUM_GDAL_VERSION:
            minimum = ".".join(str(part) for part in MINIMUM_GDAL_VERSION)
            raise GdalError(
                f"{operation} found GDAL {version}; GDAL {minimum} or newer is required"
            )
        self._versions[executable] = version
        return version

    def _supports_writable_driver(
        self,
        executable: str,
        *,
        driver: str,
        kind: Literal["vector", "raster"],
    ) -> bool:
        key = (executable, driver, kind)
        cached = self._driver_support.get(key)
        if cached is not None:
            return cached

        result = self._run(
            executable,
            ["--formats"],
            operation=f"checking {driver} support in {executable}",
        )
        prefix = f"{driver} -{kind}-"
        supported = False
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith(prefix):
                continue
            capabilities = re.search(r"\(([^)]*)\)", stripped)
            supported = capabilities is not None and "w" in capabilities.group(1)
            break
        self._driver_support[key] = supported
        return supported

    def _inspect_geotiff(
        self,
        path: Path,
        *,
        operation: str,
        include_image_structure: bool = False,
    ) -> _GdalInfo:
        arguments = ["-json"]
        if include_image_structure:
            arguments.extend(["-mdd", "IMAGE_STRUCTURE"])
        arguments.extend(["-if", "GTiff", str(path)])
        result = self._run(self._gdalinfo, arguments, operation=operation)
        try:
            info = _GdalInfo.model_validate_json(result.stdout)
        except ValidationError as exc:
            raise GdalError(
                f"{operation} returned invalid raster metadata: "
                f"{self._diagnostic(str(exc))}"
            ) from exc
        if info.driver_short_name != "GTiff":
            raise GdalError(
                f"{operation} opened driver {info.driver_short_name!r}, expected 'GTiff'"
            )
        width, height = info.size
        if width <= 0 or height <= 0:
            raise GdalError(
                f"{operation} found invalid raster dimensions {width}x{height}"
            )
        if not info.bands:
            raise GdalError(f"{operation} found no raster bands")
        for band in info.bands:
            if band.block[0] <= 0 or band.block[1] <= 0:
                raise GdalError(
                    f"{operation} found invalid block size {band.block!r} "
                    f"for band {band.band}"
                )
        return info

    def _validate_cog_output(
        self,
        *,
        source_info: _GdalInfo,
        output_info: _GdalInfo,
        source: Path,
        destination: Path,
    ) -> None:
        if output_info.size != source_info.size:
            raise GdalError(
                f"COG {destination} dimensions {output_info.size[0]}x"
                f"{output_info.size[1]} do not match source GeoTIFF {source} "
                f"dimensions {source_info.size[0]}x{source_info.size[1]}"
            )
        if len(output_info.bands) != len(source_info.bands):
            raise GdalError(
                f"COG {destination} has {len(output_info.bands)} bands, expected "
                f"{len(source_info.bands)} from source GeoTIFF {source}"
            )

        image_structure = output_info.metadata.get("IMAGE_STRUCTURE", {})
        if image_structure.get("LAYOUT") != "COG":
            raise GdalError(
                f"GDAL output {destination} does not report IMAGE_STRUCTURE LAYOUT=COG"
            )
        for band in output_info.bands:
            if band.block != (COG_BLOCK_SIZE, COG_BLOCK_SIZE):
                raise GdalError(
                    f"COG {destination} band {band.band} uses block size "
                    f"{band.block!r}, expected {COG_BLOCK_SIZE}x{COG_BLOCK_SIZE}"
                )

        overview_counts = {len(band.overviews) for band in output_info.bands}
        if len(overview_counts) != 1:
            raise GdalError(
                f"COG {destination} bands do not have a consistent overview pyramid"
            )
        overview_count = next(iter(overview_counts))
        if max(output_info.size) > COG_BLOCK_SIZE and overview_count == 0:
            raise GdalError(
                f"COG {destination} is {output_info.size[0]}x{output_info.size[1]} "
                "but does not contain internal overviews"
            )

    def _native_crs(self, info: _GdalInfo) -> str | None:
        epsg = info.stac.get("proj:epsg")
        if isinstance(epsg, int) and not isinstance(epsg, bool) and epsg > 0:
            return f"EPSG:{epsg}"
        if info.coordinate_system is None:
            return None
        wkt = info.coordinate_system.wkt
        if wkt is None or wkt.strip() == "":
            return None
        return wkt

    def _wgs84_bounds(self, info: _GdalInfo) -> RasterBounds | None:
        extent = info.wgs84_extent
        if extent is None:
            return None
        positions = [position for ring in extent.coordinates for position in ring]
        if not positions:
            return None
        if any(
            not -180 <= longitude <= 180 or not -90 <= latitude <= 90
            for longitude, latitude in positions
        ):
            return None
        return self._bounds(positions)

    def _bounds(
        self,
        positions: list[tuple[float, float]],
    ) -> RasterBounds | None:
        if any(not math.isfinite(x) or not math.isfinite(y) for x, y in positions):
            return None
        x_values = [position[0] for position in positions]
        y_values = [position[1] for position in positions]
        return min(x_values), min(y_values), max(x_values), max(y_values)

    def _validate_paths(
        self,
        source: Path,
        destination: Path,
        *,
        operation: str,
    ) -> None:
        resolved_source = self._validate_source(source, operation=operation)
        try:
            resolved_destination = destination.resolve(strict=False)
        except OSError as exc:
            raise GdalError(
                f"{operation} cannot resolve destination {destination}: {exc}"
            ) from exc
        if resolved_source == resolved_destination:
            raise GdalError(
                f"{operation} source and destination resolve to the same file {source}"
            )
        if destination.exists() or destination.is_symlink():
            raise GdalError(
                f"{operation} destination {destination} already exists; refusing to overwrite it"
            )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GdalError(
                f"{operation} cannot create destination directory "
                f"{destination.parent}: {exc}"
            ) from exc

    def _validate_directory_paths(
        self,
        source: Path,
        destination: Path,
        *,
        operation: str,
    ) -> None:
        resolved_source = self._validate_source(source, operation=operation)
        try:
            resolved_destination = destination.resolve(strict=False)
        except OSError as exc:
            raise GdalError(
                f"{operation} cannot resolve destination directory {destination}: {exc}"
            ) from exc
        if resolved_source == resolved_destination:
            raise GdalError(
                f"{operation} source and destination resolve to the same path {source}"
            )
        if destination.exists() or destination.is_symlink():
            raise GdalError(
                f"{operation} destination directory {destination} already exists; "
                "refusing to merge or overwrite tiles"
            )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GdalError(
                f"{operation} cannot create parent directory {destination.parent}: {exc}"
            ) from exc

    def _validate_source(self, source: Path, *, operation: str) -> Path:
        try:
            resolved_source = source.resolve(strict=True)
        except OSError as exc:
            raise GdalError(
                f"{operation} cannot resolve source file {source}: {exc}"
            ) from exc
        if not resolved_source.is_file():
            raise GdalError(f"{operation} source {source} is not a regular file")
        return resolved_source

    def _validate_created_file(self, path: Path, *, operation: str) -> None:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise GdalError(
                f"{operation} did not create readable output {path}: {exc}"
            ) from exc
        if not path.is_file() or size <= 0:
            raise GdalError(f"{operation} created invalid or empty output {path}")

    def _remove_partial_output(self, destination: Path) -> None:
        try:
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
        except OSError:
            pass

    def _remove_partial_directory(self, destination: Path) -> None:
        try:
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            elif destination.is_file() or destination.is_symlink():
                destination.unlink()
        except OSError:
            pass

    def _run(
        self,
        executable: str,
        arguments: list[str],
        *,
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [executable, *arguments],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise GdalError(
                f"{operation} could not start because executable {executable!r} "
                "was not found"
            ) from exc
        except OSError as exc:
            raise GdalError(
                f"{operation} could not start executable {executable!r}: {exc}"
            ) from exc
        if result.returncode != 0:
            diagnostic = result.stderr.strip() or result.stdout.strip()
            raise GdalError(
                f"{operation} failed in executable {executable!r} with exit code "
                f"{result.returncode}: {self._diagnostic(diagnostic)}"
            )
        return result

    def _diagnostic(self, value: str) -> str:
        compact = " ".join(value.split())
        if compact == "":
            return "no diagnostic output"
        if len(compact) <= 1_000:
            return compact
        return f"{compact[:997]}..."

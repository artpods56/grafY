"""Shared fixtures: small generated TIFFs, settings, and a signed-grant helper.

Nothing large is committed; every TIFF is written into `tmp_path` on demand.
"""

import hashlib
import time
import warnings
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import rasterio
from affine import Affine
from fastapi import FastAPI
from grafy_crypto.grants import Grant
from PIL import Image
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import from_origin

from grafy_tiler.app import create_app
from grafy_tiler.settings import Settings

BUCKET = "workbench-artifacts"
SIGNING_KEY = "k" * 40
SHA = "a" * 64
GRANT_HEADER = "X-Grafy-Grant"

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)

type Writer = Callable[..., Path]


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    (root / BUCKET).mkdir(parents=True)
    return root


@pytest.fixture
def settings(tmp_path: Path, storage_root: Path) -> Settings:
    return Settings(  # pyright: ignore[reportCallIssue]
        signing_keys=SIGNING_KEY,  # pyright: ignore[reportArgumentType]
        bucket=BUCKET,
        storage="local",
        local_root=storage_root,
        cache_dir=tmp_path / "cache",
        cache_max_bytes=64 * 1024 * 1024,
        render_concurrency=2,
        queue_depth=4,
        render_timeout_seconds=20,
    )


@pytest.fixture
def grant_for(storage_root: Path) -> Callable[..., Grant]:
    """Describe a file under the storage root as a grant (unsigned)."""

    def make(
        name: str, *, page: int = 0, sha: str | None = None, size: int | None = None
    ) -> Grant:
        path = storage_root / BUCKET / name
        # The real digest, as the API records it: cache keys must differ per file.
        digest = sha or hashlib.sha256(path.read_bytes()).hexdigest()
        return Grant(
            bucket=BUCKET,
            key=name,
            sha256=digest,
            byte_size=size if size is not None else path.stat().st_size,
            page=page,
            expires_at=int(time.time()) + 60,
        )

    return make


@pytest.fixture
def token_for() -> Callable[[Grant], str]:
    return lambda grant: grant.sign_grant(SIGNING_KEY.encode())


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """The app over ASGI, with its real cache and render pool."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://tiler"
        ) as http:
            yield http


@pytest.fixture
def auth(
    grant_for: Callable[..., Grant], token_for: Callable[[Grant], str]
) -> Callable[..., dict[str, str]]:
    """Sign a grant for a file in the storage root, with optional changes."""

    def headers(name: str, **changes: object) -> dict[str, str]:
        grant = replace(grant_for(name), **changes)  # pyright: ignore[reportArgumentType]
        return {GRANT_HEADER: token_for(grant)}

    return headers


def _profile(
    width: int, height: int, count: int, dtype: str, **extra: Any
) -> dict[str, Any]:
    return {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": count,
        "dtype": dtype,
        **extra,
    }


@pytest.fixture
def gray8(storage_root: Path) -> Writer:
    def write(name: str = "gray8.tif", width: int = 1300, height: int = 700) -> Path:
        path = storage_root / BUCKET / name
        ramp = np.tile(np.linspace(0, 255, width, dtype=np.uint8), (height, 1))
        with rasterio.open(path, "w", **_profile(width, height, 1, "uint8")) as ds:
            ds.write(ramp, 1)
        return path

    return write


@pytest.fixture
def rgb_tiled_with_overviews(storage_root: Path) -> Writer:
    """A tiled RGB GeoTIFF with overviews, like the large scans in production."""

    def write(name: str = "rgb.tif", width: int = 1500, height: int = 900) -> Path:
        path = storage_root / BUCKET / name
        data = np.zeros((3, height, width), dtype=np.uint8)
        data[0] = 200
        data[1] = np.tile(np.linspace(0, 255, width, dtype=np.uint8), (height, 1))
        data[2] = 40
        with rasterio.open(
            path,
            "w",
            **_profile(
                width,
                height,
                3,
                "uint8",
                tiled=True,
                blockxsize=256,
                blockysize=256,
                compress="deflate",
                photometric="RGB",
                crs="EPSG:3857",
                transform=from_origin(2_000_000, 6_800_000, 10, 10),
            ),
        ) as ds:
            ds.write(data)
            ds.build_overviews([2, 4, 8], Resampling.average)
        return path

    return write


@pytest.fixture
def rotated_geotiff(storage_root: Path) -> Writer:
    """An RGB GeoTIFF whose transform shears: pixel (x, y) is not axis-aligned.

    A window on this must still say where its own corners landed, which is what
    an affine with non-zero `b` and `d` proves.
    """

    def write(name: str = "rotated.tif", width: int = 90, height: int = 70) -> Path:
        path = storage_root / BUCKET / name
        data = np.zeros((3, height, width), dtype=np.uint8)
        data[1] = np.tile(np.arange(width, dtype=np.uint8), (height, 1))
        transform = Affine(2.0, 0.5, 500_000.0, -0.5, -2.0, 4_000_000.0)
        with rasterio.open(
            path,
            "w",
            **_profile(
                width,
                height,
                3,
                "uint8",
                photometric="RGB",
                crs="EPSG:32632",
                transform=transform,
            ),
        ) as ds:
            ds.write(data)
        return path

    return write


@pytest.fixture
def gray_internal_mask(storage_root: Path) -> Writer:
    """Grayscale with a per-dataset internal mask: transparent in one square."""

    def write(name: str = "gray-mask.tif", size: int = 64) -> Path:
        path = storage_root / BUCKET / name
        pixels = np.full((size, size), 9, dtype=np.uint8)
        valid = np.full((size, size), 255, dtype=np.uint8)
        valid[size // 2 :, size // 2 :] = 0
        with rasterio.open(
            path,
            "w",
            **_profile(
                size, size, 1, "uint8", tiled=True, blockxsize=16, blockysize=16
            ),
        ) as ds:
            ds.write(pixels, 1)
            ds.write_mask(valid)
        return path

    return write


@pytest.fixture
def nodata_gray(storage_root: Path) -> Writer:
    """Grayscale whose value 0 is nodata: the value stays, the alpha marks it."""

    def write(name: str = "nodata.tif", size: int = 40) -> Path:
        path = storage_root / BUCKET / name
        pixels = np.full((size, size), 7, dtype=np.uint8)
        pixels[size // 2, size // 2] = 0
        with rasterio.open(
            path, "w", **_profile(size, size, 1, "uint8", nodata=0)
        ) as ds:
            ds.write(pixels, 1)
        return path

    return write


@pytest.fixture
def coarsely_tiled_gray(storage_root: Path) -> Writer:
    """A scan stored in one 1024 px tile: any window decodes that whole tile.

    Tiles are usually 128 or 256; coarse ones are what make a small window cost
    a large decode, which is the case the decode bound exists for.
    """

    def write(name: str = "coarse.tif", width: int = 900, height: int = 700) -> Path:
        path = storage_root / BUCKET / name
        rng = np.random.default_rng(7)
        with rasterio.open(
            path,
            "w",
            **_profile(
                width, height, 1, "uint8", tiled=True, blockxsize=1024, blockysize=1024
            ),
        ) as ds:
            ds.write(rng.integers(0, 256, (height, width), dtype=np.uint8), 1)
        return path

    return write


@pytest.fixture
def rgba(storage_root: Path) -> Writer:
    def write(name: str = "rgba.tif", width: int = 600, height: int = 400) -> Path:
        path = storage_root / BUCKET / name
        data = np.zeros((4, height, width), dtype=np.uint8)
        data[0] = 250
        data[3, :, : width // 2] = 255
        with rasterio.open(
            path,
            "w",
            **_profile(width, height, 4, "uint8", photometric="RGB", alpha="YES"),
        ) as ds:
            ds.write(data)
        return path

    return write


@pytest.fixture
def bilevel_lines(storage_root: Path) -> Writer:
    """A striped CCITT G4 scan: one-pixel black lines on white, like text."""

    def write(name: str = "g4.tif", width: int = 3000, height: int = 2000) -> Path:
        path = storage_root / BUCKET / name
        scan = np.ones((height, width), dtype=np.uint8)
        scan[::4, :] = 0
        with rasterio.open(
            path,
            "w",
            **_profile(width, height, 1, "uint8", nbits=1, compress="CCITTFAX4"),
        ) as ds:
            ds.write(scan, 1)
        return path

    return write


@pytest.fixture
def uint16(storage_root: Path) -> Writer:
    def write(name: str = "u16.tif", width: int = 800, height: int = 600) -> Path:
        path = storage_root / BUCKET / name
        ramp = np.tile(np.linspace(1000, 5000, width, dtype=np.uint16), (height, 1))
        with rasterio.open(path, "w", **_profile(width, height, 1, "uint16")) as ds:
            ds.write(ramp, 1)
        return path

    return write


@pytest.fixture
def float32(storage_root: Path) -> Writer:
    def write(name: str = "f32.tif", width: int = 500, height: int = 400) -> Path:
        path = storage_root / BUCKET / name
        ramp = np.tile(np.linspace(-1.5, 2.5, width, dtype=np.float32), (height, 1))
        with rasterio.open(path, "w", **_profile(width, height, 1, "float32")) as ds:
            ds.write(ramp, 1)
        return path

    return write


@pytest.fixture
def palette(storage_root: Path) -> Writer:
    def write(name: str = "palette.tif", width: int = 400, height: int = 300) -> Path:
        path = storage_root / BUCKET / name
        indexes = np.zeros((height, width), dtype=np.uint8)
        indexes[:, width // 2 :] = 1
        with rasterio.open(path, "w", **_profile(width, height, 1, "uint8")) as ds:
            ds.write(indexes, 1)
            ds.write_colormap(
                1, {0: (255, 0, 0, 255), 1: (0, 0, 255, 255), 2: (0, 255, 0, 255)}
            )
        return path

    return write


@pytest.fixture
def rgb_alpha_ramp(storage_root: Path) -> Writer:
    """RGB whose alpha band runs 0..255 across the width, not a boolean mask."""

    def write(name: str = "alpha-ramp.tif", width: int = 90, height: int = 30) -> Path:
        path = storage_root / BUCKET / name
        data = np.zeros((4, height, width), dtype=np.uint8)
        data[0] = 250
        data[1] = np.tile(np.arange(width, dtype=np.uint8), (height, 1))
        data[3] = np.tile(np.arange(width, dtype=np.uint8), (height, 1))
        with rasterio.open(
            path,
            "w",
            **_profile(width, height, 4, "uint8", photometric="RGB", alpha="YES"),
        ) as ds:
            ds.write(data)
        return path

    return write


@pytest.fixture
def cmyk(storage_root: Path) -> Writer:
    """Raw four-band CMYK (cyan, magenta, yellow, black colour interpretation)."""

    def write(name: str = "cmyk.tif", dtype: str = "uint8") -> Path:
        path = storage_root / BUCKET / name
        top = np.iinfo(dtype).max
        data = np.zeros((4, 120, 160), dtype=dtype)
        data[0, :, :80] = top  # full cyan on the left half
        data[3, :, 80:] = top  # full black on the right half
        with rasterio.open(
            path, "w", **_profile(160, 120, 4, dtype, photometric="MINISBLACK")
        ) as ds:
            ds.write(data)
        with rasterio.open(path, "r+") as ds:
            ds.colorinterp = [
                ColorInterp.cyan,
                ColorInterp.magenta,
                ColorInterp.yellow,
                ColorInterp.black,
            ]
        return path

    return write


@pytest.fixture
def cmyk_libtiff(storage_root: Path) -> Writer:
    """Pillow's CMYK TIFF, which GDAL itself converts to RGBA while reading."""

    def write(name: str = "cmyk-libtiff.tif") -> Path:
        path = storage_root / BUCKET / name
        Image.new("CMYK", (300, 200), (255, 0, 0, 0)).save(path, compression="raw")
        return path

    return write


@pytest.fixture
def multipage(storage_root: Path) -> Writer:
    def write(name: str = "pages.tif") -> Path:
        path = storage_root / BUCKET / name
        colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        pages = [
            Image.new("RGB", (320 + 80 * i, 240), colour)
            for i, colour in enumerate(colours)
        ]
        pages[0].save(
            path,
            save_all=True,
            append_images=pages[1:],
            compression="tiff_adobe_deflate",
        )
        return path

    return write


@pytest.fixture
def garbage(storage_root: Path) -> Writer:
    def write(name: str = "garbage.tif") -> Path:
        path = storage_root / BUCKET / name
        path.write_bytes(b"this is not a tiff" * 50)
        return path

    return write


@pytest.fixture(autouse=True)
def _gdal_environment(settings: Settings) -> Iterator[None]:
    import os

    before = dict(os.environ)
    settings.apply_gdal_environment()
    yield
    os.environ.clear()
    os.environ.update(before)

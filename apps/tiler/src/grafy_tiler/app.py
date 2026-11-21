"""HTTP surface of the tiler. Internal only: the API is the public entry.

Every data route takes exactly one input about what to read, the signed
``X-Grafy-Grant`` header (see :mod:`grafy_crypto.grants`). The mosaic route
carries its multi-source grant in a JSON body instead, because 64 sources do not
fit a header. There is no URL, path or bucket parameter anywhere, so there is
nothing to point at another host.
"""

import faulthandler
import logging
import time
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse
from grafy_crypto.grants import Grant, GrantError, MosaicGrant
from pydantic import BaseModel, BeforeValidator, Field
from rasterio.errors import NotGeoreferencedWarning
from rio_tiler.errors import TileOutsideBounds
from titiler.core.errors import add_exception_handlers
from titiler.core.middleware import TotalTimeMiddleware

from grafy_tiler.cache import DiskCache
from grafy_tiler.raster import (
    RENDERER_VERSION,
    PageNotFound,
    SourceError,
    SourceMismatch,
    SourceTooLarge,
    TileFormat,
)
from grafy_tiler.service import (
    THUMBNAIL_EDGES,
    Overloaded,
    RenderTimeout,
    TileNotFound,
    TileService,
)
from grafy_tiler.settings import Settings
from grafy_tiler.window import (
    UnsupportedPixelFormat,
    WindowOutOfBounds,
    WindowTooLarge,
)

logger = logging.getLogger("grafy_tiler")

_MEDIA_TYPES: dict[str, str] = {"jpg": "image/jpeg", "png": "image/png"}
_RETRY_AFTER_SECONDS = "2"


def _service_of(request: Request) -> TileService:
    return request.app.state.service


def _grant_of(
    request: Request,
    token: Annotated[str | None, Header(alias="X-Grafy-Grant")] = None,
) -> Grant:
    config: Settings = request.app.state.settings
    if token is None:
        raise HTTPException(status_code=403, detail="grant required")
    try:
        return Grant.verify_grant(
            token,
            keys=config.signing_key_values,
            bucket=config.bucket,
            now=int(time.time()),
            skew_seconds=config.grant_clock_skew_seconds,
            max_source_bytes=config.max_source_bytes,
        )
    except GrantError as error:
        # Never echo why: the caller is the API, and the log has the reason.
        logger.warning("grant refused: %s", error)
        raise HTTPException(status_code=403, detail="grant refused") from error


Service = Annotated[TileService, Depends(_service_of)]
Granted = Annotated[Grant, Depends(_grant_of)]

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    try:
        request.app.state.cache.check_writable()
    except OSError as error:
        logger.error("cache is not writable: %s", error)
        raise HTTPException(status_code=503, detail="cache not writable") from error
    return {"status": "ok", "renderer": RENDERER_VERSION}


@router.get("/info")
async def info(grant: Granted, service: Service) -> dict[str, object]:
    return (await service.info(grant)).to_json_dict()


@router.get("/tiles/{z}/{x}/{y}.{extension}")
async def tile(
    grant: Granted,
    service: Service,
    z: Annotated[int, Path(ge=0, le=40)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    extension: str,
) -> Response:
    if extension not in _MEDIA_TYPES:
        raise TileNotFound("unknown tile format")
    tile_format: TileFormat = "jpg" if extension == "jpg" else "png"
    return _image(await service.tile(grant, z, x, y, tile_format), tile_format)


@router.get("/geo/tiles/{z}/{x}/{y}.{extension}")
async def geo_tile(
    grant: Granted,
    service: Service,
    z: str,
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    extension: str,
) -> Response:
    if extension not in _MEDIA_TYPES:
        raise TileNotFound("unknown tile format")
    try:
        zoom = int(_integer_query(z))
    except ValueError as error:
        raise TileNotFound("invalid Web Mercator zoom") from error
    requested: TileFormat = "jpg" if extension == "jpg" else "png"
    data, tile_format = await service.geo_tile(grant, zoom, x, y, requested)
    return _image(data, tile_format)


class MosaicGrantRequest(BaseModel):
    grant: str = Field(min_length=1, max_length=65_536)


@router.post("/geo/mosaic/tiles/{z}/{x}/{y}.{extension}")
async def geo_mosaic_tile(
    body: MosaicGrantRequest,
    request: Request,
    service: Service,
    z: str,
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    extension: str,
) -> Response:
    config: Settings = request.app.state.settings
    try:
        grant = MosaicGrant.verify_grant(
            body.grant,
            keys=config.signing_key_values,
            bucket=config.bucket,
            now=int(time.time()),
            skew_seconds=config.grant_clock_skew_seconds,
            max_source_bytes=config.max_source_bytes,
        )
    except GrantError as error:
        logger.warning("mosaic grant refused: %s", error)
        raise HTTPException(status_code=403, detail="grant refused") from error
    if extension not in _MEDIA_TYPES:
        raise TileNotFound("unknown tile format")
    try:
        zoom = int(_integer_query(z))
    except ValueError as error:
        raise TileNotFound("invalid Web Mercator zoom") from error
    requested: TileFormat = "jpg" if extension == "jpg" else "png"
    data, tile_format = await service.geo_mosaic_tile(grant, zoom, x, y, requested)
    return _image(data, tile_format)


@router.get("/thumbnail")
async def thumbnail(
    grant: Granted,
    service: Service,
    edge: int = 256,
) -> Response:
    if edge not in THUMBNAIL_EDGES:
        raise HTTPException(
            status_code=422, detail=f"edge must be one of {list(THUMBNAIL_EDGES)}"
        )
    data, tile_format = await service.thumbnail(grant, edge)
    return _image(data, tile_format)


def _integer_query(value: object) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("expected an unsigned decimal integer")
    return value


PixelInteger = Annotated[int, BeforeValidator(_integer_query)]


@router.get("/window")
async def window(
    grant: Granted,
    service: Service,
    col: Annotated[PixelInteger, Query(ge=0)],
    row: Annotated[PixelInteger, Query(ge=0)],
    width: Annotated[PixelInteger, Query(ge=1)],
    height: Annotated[PixelInteger, Query(ge=1)],
) -> Response:
    """Exact source pixels of a rectangle, with where they came from.

    Half-open `[col, col+width) x [row, row+height)` on the granted page, read
    1:1 and never clipped, padded, stretched or resampled. The
    ``X-Grafy-Window`` header carries the rectangle back plus the affine that
    maps crop-local pixel corners into the source CRS, both null when the page
    is not usefully georeferenced.
    """
    read = await service.window(grant, col, row, width, height)
    return Response(
        content=read.png,
        media_type="image/png",
        headers={"X-Grafy-Window": read.header},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()  # pyright: ignore[reportCallIssue]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # A native crash (a GDAL or codec bug) otherwise leaves no trace but a
        # dead worker. This dumps the Python stack of every thread to stderr.
        faulthandler.enable()
        # Every scan without georeferencing would warn once per tile.
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        resolved.apply_gdal_environment()
        cache = DiskCache(resolved.cache_dir, resolved.cache_max_bytes)
        service = TileService(resolved, cache)
        app.state.settings = resolved
        app.state.cache = cache
        app.state.service = service
        try:
            yield
        finally:
            service.shutdown()

    app = FastAPI(
        title="Grafy tiler",
        lifespan=lifespan,
        docs_url="/docs" if resolved.docs_enabled else None,
        redoc_url="/redoc" if resolved.docs_enabled else None,
        openapi_url="/openapi.json" if resolved.docs_enabled else None,
    )
    app.add_middleware(TotalTimeMiddleware)
    add_exception_handlers(
        app,
        {
            TileOutsideBounds: 404,
            TileNotFound: 404,
            PageNotFound: 404,
            SourceError: 422,
            SourceMismatch: 409,
            SourceTooLarge: 413,
            WindowOutOfBounds: 422,
            WindowTooLarge: 413,
            UnsupportedPixelFormat: 415,
        },
    )

    @app.exception_handler(Overloaded)
    @app.exception_handler(RenderTimeout)
    async def _retry_later(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": type(error).__name__},
            status_code=503,
            headers={"Retry-After": _RETRY_AFTER_SECONDS},
        )

    app.include_router(router)
    return app


def _image(data: bytes, tile_format: str) -> Response:
    return Response(
        content=data,
        media_type=_MEDIA_TYPES[tile_format],
        headers={"X-Grafy-Renderer": RENDERER_VERSION},
    )

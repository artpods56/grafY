"""Cache-first tile, thumbnail and info service with bounded rendering.

Request path for a tile::

    disk cache hit  -> bytes (no storage access at all)
    miss            -> image info (memory, then disk, then read the header)
                    -> single-flight render on a bounded thread pool
                    -> cache write -> bytes
"""

import asyncio
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from typing import Any, Final

from rasterio.errors import RasterioError
from rasterio.io import DatasetReader, MemoryFile

from .cache import DiskCache
from .grant import Grant
from .raster import (
    RENDERER_VERSION,
    ImageInfo,
    SourceError,
    TileFormat,
    describe,
    level_size,
    open_page,
    pixel_window,
    source_path,
    thumbnail_size,
    tile_window,
)
from .render import render_region
from .settings import Settings

THUMBNAIL_EDGES: Final = (128, 256, 512, 1024)
_INFO_MEMORY_ENTRIES: Final = 256
_INVALID_MEMORY_ENTRIES: Final = 256
_INVALID_TTL_SECONDS: Final = 60.0


class TileNotFound(Exception):
    """The level, tile or output format does not exist for this image."""


class Overloaded(Exception):
    """Too many renders are waiting; the caller should retry shortly."""


class RenderTimeout(Exception):
    """A render outlived its time budget."""


class RenderPool:
    """Bounded render concurrency plus a bounded wait queue.

    A timed-out render keeps its slot until the thread actually finishes, so the
    concurrency limit is an honest bound on running work, not on waiting callers.
    """

    def __init__(self, concurrency: int, queue_depth: int, timeout: float) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="render"
        )
        self._slots = asyncio.Semaphore(concurrency)
        self._capacity = concurrency + queue_depth
        self._pending = 0
        self._timeout = timeout

    @property
    def pending(self) -> int:
        return self._pending

    async def run[T](self, work: Callable[[], T]) -> T:
        if self._pending >= self._capacity:
            raise Overloaded
        self._pending += 1
        try:
            await self._slots.acquire()
        except BaseException:
            self._pending -= 1
            raise
        future = asyncio.get_running_loop().run_in_executor(self._executor, work)
        future.add_done_callback(self._finished)  # pyright: ignore[reportArgumentType]
        try:
            return await asyncio.wait_for(asyncio.shield(future), self._timeout)
        except TimeoutError as error:
            raise RenderTimeout from error

    def _finished(self, future: "asyncio.Future[Any]") -> None:
        self._pending -= 1
        self._slots.release()
        if not future.cancelled():
            # Mark the outcome as seen even when every waiter has gone away.
            _ = future.exception()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class SingleFlight:
    """Concurrent callers for one key share one in-flight computation."""

    def __init__(self) -> None:
        self._flights: dict[str, asyncio.Task[Any]] = {}

    @property
    def in_flight(self) -> int:
        return len(self._flights)

    async def do[T](self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        flight = self._flights.get(key)
        if flight is None:
            flight = asyncio.ensure_future(factory())
            self._flights[key] = flight
            flight.add_done_callback(partial(self._done, key))
        # Shielded: one caller going away must not cancel the others' result.
        return await asyncio.shield(flight)

    def _done(self, key: str, flight: "asyncio.Task[Any]") -> None:
        _ = self._flights.pop(key, None)
        if not flight.cancelled():
            _ = flight.exception()


class TileService:
    def __init__(
        self,
        settings: Settings,
        cache: DiskCache,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._pool = RenderPool(
            settings.render_concurrency,
            settings.queue_depth,
            settings.render_timeout_seconds,
        )
        self._flights = SingleFlight()
        self._clock = clock
        self._infos: OrderedDict[str, ImageInfo] = OrderedDict()
        self._invalid: OrderedDict[str, float] = OrderedDict()

    @property
    def pool(self) -> RenderPool:
        return self._pool

    def shutdown(self) -> None:
        self._pool.shutdown()

    # -- public operations ------------------------------------------------

    async def info(self, grant: Grant) -> ImageInfo:
        key = _info_key(grant)
        known = self._infos.get(key)
        if known is not None:
            self._infos.move_to_end(key)
            return known
        stored = await asyncio.to_thread(self._cache.get, key)
        if stored is not None:
            info = ImageInfo.from_json_dict(json.loads(stored))
        else:
            self._raise_if_known_invalid(key)
            info = await self._flights.do(key, partial(self._read_info, grant, key))
        self._infos[key] = info
        while len(self._infos) > _INFO_MEMORY_ENTRIES:
            _ = self._infos.popitem(last=False)
        return info

    async def tile(
        self, grant: Grant, level: int, x: int, y: int, tile_format: TileFormat
    ) -> bytes:
        key = f"tile:{RENDERER_VERSION}:{grant.sha256}:{grant.page}:{tile_format}:{level}/{x}/{y}"
        cached = await asyncio.to_thread(self._cache.get, key)
        if cached is not None:
            return cached
        info = await self.info(grant)
        if tile_format != info.tile_format:
            raise TileNotFound(f"tiles of this image are {info.tile_format}")
        use_overview = info.overview_level is not None and level <= info.overview_level
        # Level sizes round up at every halving, so the same check holds for
        # the overview raster and the full image.
        if (
            tile_window(
                info.width, info.height, info.max_level, info.tile_size, level, x, y
            )
            is None
        ):
            raise TileNotFound("tile is outside the image")
        overview = await self._overview(grant, info) if use_overview else None
        return await self._flights.do(
            key,
            partial(self._render_tile, grant, info, level, x, y, key, overview),
        )

    async def thumbnail(self, grant: Grant, edge: int) -> tuple[bytes, TileFormat]:
        info = await self.info(grant)
        key = f"thumb:{RENDERER_VERSION}:{grant.sha256}:{grant.page}:{info.tile_format}:{edge}"
        cached = await asyncio.to_thread(self._cache.get, key)
        if cached is not None:
            return cached, info.tile_format
        overview = (
            await self._overview(grant, info)
            if info.overview_level is not None
            else None
        )
        data = await self._flights.do(
            key, partial(self._render_thumbnail, grant, info, edge, key, overview)
        )
        return data, info.tile_format

    # -- info -------------------------------------------------------------

    async def _read_info(self, grant: Grant, key: str) -> ImageInfo:
        def work() -> ImageInfo:
            return describe(
                source_path(self._settings, grant), grant.page, self._settings
            )

        try:
            info = await self._pool.run(work)
        except (SourceError, RasterioError) as error:
            self._remember_invalid(key)
            raise SourceError("not a readable TIFF") from error
        document = json.dumps(info.to_json_dict(), separators=(",", ":")).encode()
        await asyncio.to_thread(self._cache.put, key, document)
        return info

    def _remember_invalid(self, key: str) -> None:
        self._invalid[key] = self._clock() + _INVALID_TTL_SECONDS
        self._invalid.move_to_end(key)
        while len(self._invalid) > _INVALID_MEMORY_ENTRIES:
            _ = self._invalid.popitem(last=False)

    def _raise_if_known_invalid(self, key: str) -> None:
        expires_at = self._invalid.get(key)
        if expires_at is None:
            return
        if self._clock() < expires_at:
            raise SourceError("not a readable TIFF")
        del self._invalid[key]

    # -- rendering --------------------------------------------------------

    async def _render_tile(
        self,
        grant: Grant,
        info: ImageInfo,
        level: int,
        x: int,
        y: int,
        key: str,
        overview: bytes | None,
    ) -> bytes:
        def work() -> bytes:
            with self._source(grant, info, overview) as (ds, source_info, top_level):
                placed = tile_window(
                    source_info.width,
                    source_info.height,
                    top_level,
                    info.tile_size,
                    level,
                    x,
                    y,
                )
                if placed is None:
                    raise TileNotFound("tile is outside the image")
                window, out_width, out_height = placed
                data = render_region(
                    ds,
                    source_info,
                    window,
                    out_width,
                    out_height,
                    tile_format=info.tile_format,
                    jpeg_quality=self._settings.jpeg_quality,
                )
            self._cache.put(key, data)
            return data

        return await self._render(work)

    async def _render_thumbnail(
        self,
        grant: Grant,
        info: ImageInfo,
        edge: int,
        key: str,
        overview: bytes | None,
    ) -> bytes:
        def work() -> bytes:
            with self._source(grant, info, overview) as (ds, source_info, _):
                out_width, out_height = thumbnail_size(info.width, info.height, edge)
                data = render_region(
                    ds,
                    source_info,
                    pixel_window(0, 0, source_info.width, source_info.height),
                    out_width,
                    out_height,
                    tile_format=info.tile_format,
                    jpeg_quality=self._settings.jpeg_quality,
                )
            self._cache.put(key, data)
            return data

        return await self._render(work)

    async def _render(self, work: Callable[[], bytes]) -> bytes:
        try:
            return await self._pool.run(work)
        except RasterioError as error:
            raise SourceError("not a readable TIFF") from error

    # -- lazy overview ----------------------------------------------------

    async def _overview(self, grant: Grant, info: ImageInfo) -> bytes:
        """A lossless PNG of at most 2048 px, built once on first need.

        It is cached and evictable like any other entry; if it is evicted the
        next request rebuilds it. This is not an import-time conversion.
        """
        assert info.overview_level is not None
        key = f"overview:{RENDERER_VERSION}:{grant.sha256}:{grant.page}"
        cached = await asyncio.to_thread(self._cache.get, key)
        if cached is not None:
            return cached
        return await self._flights.do(
            key, partial(self._build_overview, grant, info, key)
        )

    async def _build_overview(self, grant: Grant, info: ImageInfo, key: str) -> bytes:
        assert info.overview_level is not None
        out_width, out_height = level_size(
            info.width, info.height, info.max_level, info.overview_level
        )

        def work() -> bytes:
            with self._source(grant, info, None) as (ds, source_info, _):
                data = render_region(
                    ds,
                    source_info,
                    pixel_window(0, 0, info.width, info.height),
                    out_width,
                    out_height,
                    tile_format="png",
                    jpeg_quality=self._settings.jpeg_quality,
                )
            self._cache.put(key, data)
            return data

        return await self._render(work)

    @contextmanager
    def _source(
        self, grant: Grant, info: ImageInfo, overview: bytes | None
    ) -> Iterator[tuple[DatasetReader, ImageInfo, int]]:
        """Open the image, or its cached overview, with the info that describes
        the opened raster and the pyramid level at which it is 1:1."""
        if overview is None:
            with open_page(source_path(self._settings, grant), info.page) as ds:
                yield ds, info, info.max_level
            return
        assert info.overview_level is not None
        with MemoryFile(overview) as memory, memory.open() as ds:
            # The overview is already display-ready 8-bit; only its shape,
            # band layout and transparency matter to the renderer.
            yield (
                ds,
                replace(
                    info,
                    width=ds.width,
                    height=ds.height,
                    band_count=ds.count,
                    dtype="uint8",
                    bit_depth=8,
                    kind="rgb" if ds.count >= 3 else "gray",
                    resampling="average",
                    overview_count=0,
                    overview_level=None,
                    value_range=None,
                    palette=None,
                ),
                info.overview_level,
            )


def _info_key(grant: Grant) -> str:
    return f"info:{RENDERER_VERSION}:{grant.sha256}:{grant.page}"

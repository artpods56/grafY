import asyncio
import threading
from collections.abc import AsyncIterator, Callable

import pytest

from grafy_tiler import service as service_module
from grafy_tiler.cache import DiskCache
from grafy_tiler.grant import Grant
from grafy_tiler.raster import SourceError
from grafy_tiler.service import (
    Overloaded,
    RenderPool,
    RenderTimeout,
    SingleFlight,
    TileNotFound,
    TileService,
)
from grafy_tiler.settings import Settings

from .conftest import Writer


@pytest.fixture
async def make_service(settings: Settings) -> AsyncIterator[Callable[..., TileService]]:
    created: list[TileService] = []

    def make(**changes: object) -> TileService:
        configured = settings.model_copy(update=changes)
        service = TileService(
            configured, DiskCache(configured.cache_dir, configured.cache_max_bytes)
        )
        created.append(service)
        return service

    yield make
    for service in created:
        service.shutdown()


# -- bounded rendering --------------------------------------------------------


async def test_pool_refuses_work_beyond_the_queue_without_waiting() -> None:
    pool = RenderPool(concurrency=1, queue_depth=1, timeout=30)
    started, release = threading.Event(), threading.Event()

    def block() -> str:
        started.set()
        assert release.wait(10)
        return "done"

    running = asyncio.ensure_future(pool.run(block))
    await asyncio.to_thread(started.wait, 10)
    queued = asyncio.ensure_future(pool.run(lambda: "queued"))
    await asyncio.sleep(0)  # let the queued call register as pending
    assert pool.pending == 2

    with pytest.raises(Overloaded):
        await pool.run(lambda: "refused")

    release.set()
    assert await running == "done"
    assert await queued == "queued"
    assert pool.pending == 0
    pool.shutdown()


async def test_a_timed_out_render_keeps_its_slot_until_the_thread_ends() -> None:
    pool = RenderPool(concurrency=1, queue_depth=1, timeout=0.05)
    started, release = threading.Event(), threading.Event()

    def block() -> None:
        started.set()
        assert release.wait(10)

    with pytest.raises(RenderTimeout):
        await pool.run(block)
    assert started.is_set()
    assert pool.pending == 1  # the caller gave up; the thread is still running

    # The next call queues behind the slot and only runs once the thread ends.
    after = asyncio.ensure_future(pool.run(lambda: "after"))
    await asyncio.sleep(0)
    assert not after.done()
    release.set()
    assert await after == "after"
    await asyncio.sleep(0)
    assert pool.pending == 0
    pool.shutdown()


# -- single flight -------------------------------------------------------------


async def test_concurrent_callers_share_one_computation() -> None:
    flights = SingleFlight()
    gate = asyncio.Event()
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        return "value"

    waiting = [asyncio.ensure_future(flights.do("k", compute)) for _ in range(5)]
    await asyncio.sleep(0)
    assert flights.in_flight == 1
    gate.set()
    assert await asyncio.gather(*waiting) == ["value"] * 5
    assert calls == 1
    assert flights.in_flight == 0


async def test_a_cancelled_caller_does_not_cancel_the_others() -> None:
    flights = SingleFlight()
    gate = asyncio.Event()

    async def compute() -> str:
        await gate.wait()
        return "value"

    first = asyncio.ensure_future(flights.do("k", compute))
    second = asyncio.ensure_future(flights.do("k", compute))
    await asyncio.sleep(0)
    first.cancel()
    gate.set()
    assert await second == "value"


async def test_a_failure_is_shared_then_forgotten() -> None:
    flights = SingleFlight()
    gate = asyncio.Event()
    calls = 0

    async def broken() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        raise ValueError("boom")

    waiting = [asyncio.ensure_future(flights.do("k", broken)) for _ in range(3)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*waiting, return_exceptions=True)
    assert all(isinstance(r, ValueError) for r in results) and calls == 1
    with pytest.raises(ValueError):
        await flights.do("k", broken)
    assert calls == 2


# -- the service ------------------------------------------------------------------


async def test_a_tile_is_cached_and_then_served_without_the_source(
    make_service: Callable[..., TileService],
    grant_for: Callable[..., Grant],
    gray8: Writer,
) -> None:
    path = gray8()
    grant = grant_for(path.name)
    service = make_service()
    first = await service.tile(grant, 11, 0, 0, "jpg")
    path.unlink()  # storage can disappear; the cache is digest-addressed

    assert await service.tile(grant, 11, 0, 0, "jpg") == first
    # A fresh process sharing the volume does too, info included.
    restarted = make_service()
    assert await restarted.tile(grant, 11, 0, 0, "jpg") == first
    assert (await restarted.info(grant)).width == 1300


async def test_wrong_format_and_out_of_range_tiles_do_not_exist(
    make_service: Callable[..., TileService],
    grant_for: Callable[..., Grant],
    gray8: Writer,
) -> None:
    grant = grant_for(gray8().name)
    service = make_service()
    with pytest.raises(TileNotFound, match="jpg"):
        await service.tile(grant, 11, 0, 0, "png")
    with pytest.raises(TileNotFound):
        await service.tile(grant, 11, 3, 0, "jpg")
    with pytest.raises(TileNotFound):
        await service.tile(grant, 12, 0, 0, "jpg")


async def test_concurrent_requests_for_one_tile_render_it_once(
    make_service: Callable[..., TileService],
    grant_for: Callable[..., Grant],
    gray8: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grant = grant_for(gray8().name)
    service = make_service()
    await service.info(grant)  # keep the count about the tile alone
    renders = 0
    real = service_module.render_region

    def counting(*args: object, **kwargs: object) -> bytes:
        nonlocal renders
        renders += 1
        return real(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(service_module, "render_region", counting)
    results = await asyncio.gather(
        *(service.tile(grant, 10, 0, 0, "jpg") for _ in range(8))
    )
    assert len({bytes(r) for r in results}) == 1
    assert renders == 1


async def test_thumbnail_sizes_and_format(
    make_service: Callable[..., TileService],
    grant_for: Callable[..., Grant],
    gray8: Writer,
) -> None:
    import io

    from PIL import Image

    grant = grant_for(gray8().name)
    data, tile_format = await make_service().thumbnail(grant, 256)
    assert tile_format == "jpg"
    assert Image.open(io.BytesIO(data)).size == (256, 138)


async def test_unreadable_sources_are_remembered_briefly(
    settings: Settings,
    grant_for: Callable[..., Grant],
    garbage: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    service = TileService(
        settings,
        DiskCache(settings.cache_dir, settings.cache_max_bytes),
        clock=lambda: now,
    )
    grant = grant_for(garbage().name)
    reads = 0
    real = service_module.describe

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal reads
        reads += 1
        return real(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(service_module, "describe", counting)
    try:
        for _ in range(3):
            with pytest.raises(SourceError):
                await service.info(grant)
        assert reads == 1
        now += 61
        with pytest.raises(SourceError):
            await service.info(grant)
        assert reads == 2
    finally:
        service.shutdown()


async def test_large_scan_without_overviews_is_served_from_a_lazy_overview(
    make_service: Callable[..., TileService],
    grant_for: Callable[..., Grant],
    bilevel_lines: Writer,
) -> None:
    import io

    from PIL import Image

    path = bilevel_lines()  # 3000 x 2000, striped, no overviews
    grant = grant_for(path.name)
    service = make_service(overview_min_pixels=2048)
    info = await service.info(grant)
    assert info.overview_level is not None and info.overview_level < info.max_level

    low = info.overview_level
    first = await service.tile(grant, low, 0, 0, "png")  # builds the overview
    assert Image.open(io.BytesIO(first)).size[0] <= 512

    path.unlink()  # from here on, low-zoom work must not touch the source
    other_level = await service.tile(grant, low - 1, 0, 0, "png")
    assert other_level
    thumbnail, _ = await service.thumbnail(grant, 128)
    assert Image.open(io.BytesIO(thumbnail)).size == (128, 85)
    # Full-resolution tiles still need the source.
    with pytest.raises(SourceError):
        await service.tile(grant, info.max_level, 0, 0, "png")

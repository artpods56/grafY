"""Two operation shapes on one cache, with synthetic providers.

The point of this file is that nothing about :class:`~grafy_core.provider_cache.ProviderCache`
is shaped after a particular node. Both operations below reach a provider through
the same wrapper and the same store, and differ only in what their caller can
honestly say a request is:

- a **lazy window** over a TIFF, where the request is the file's content digest,
  the page, the window bounds in page pixels, the preprocessing version that turns
  those pixels into what the provider sees, and the detection settings;
- a **prepared crop** from a polygon selection, where the bytes are already in
  hand, so the request is their digest plus the recognizer revision, the language,
  and the options that were sent.

Neither the fake TIFF reader nor the fake recognition client mentions a cache.
They are the same objects whether or not the binding wrapped them, which is the
property the real nodes have to keep.
"""

import hashlib
import inspect
import math
from collections.abc import Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, JsonValue, TypeAdapter
import pytest

from grafy_core.provider_cache import (
    CacheSpec,
    InMemoryCacheStore,
    ProviderCache,
    cached_call,
)

WORKSPACE = uuid4()

#: What the pixel transform applied before the provider sees a window is worth to
#: the key: a window read under a different transform is a different question.
WINDOW_PREPROCESSING_VERSION = "window-png@1"
CROP_PREPROCESSING_VERSION = "crop-normalise@1"
#: Stand-ins for an implementation digest of the request/response code, which is
#: what a real binding puts in ``revision``.
WINDOW_REVISION = "craft-cv4"
RECOGNIZER_REVISION = "recognizer-2.4"

TILE_PIXELS = 128


class Window(BaseModel):
    """A rectangle of one TIFF page, in page pixels."""

    page: int
    x0: int
    y0: int
    x1: int
    y1: int


class PreparedCrop(BaseModel):
    """Bytes already cut, normalised and ready to send."""

    png: bytes
    label: str


class RecognizeOptions(BaseModel):
    language: str
    preserve_layout: bool


class CropReading(BaseModel):
    text: str
    confidence: float


class FakeTiff:
    """Stands in for a stored TIFF: reading a window costs something."""

    def __init__(self, content: bytes, *, pages: int = 1) -> None:
        self.content = content
        self.pages = pages
        self.read_windows: list[Window] = []

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    async def read_window_png(self, window: Window) -> bytes:
        if window.page >= self.pages:
            raise IndexError(f"page {window.page} is not in a {self.pages}-page file")
        self.read_windows.append(window)
        bounds = f"{window.page}:{window.x0},{window.y0},{window.x1},{window.y1}"
        return f"png-of-{bounds}-from-{self.sha256[:8]}".encode()


def make_window_operation(
    service: FakeDetectionService,
) -> Callable[[FakeTiff, Window], Awaitable[list[str]]]:
    """The lazy window read: bytes are fetched here, on the way to the provider.

    It reads the page-anchored tile because that is what :func:`window_identity`
    names. A key over the tile with a read of the raw selection would serve one
    rectangle's boxes for another's, which is the one mistake a cache cannot undo
    later: whatever the identity says is what the work has to be about.
    """

    async def detect_window(source: FakeTiff, window: Window) -> list[str]:
        tile = page_anchored_tile(window)
        return await service.detect(await source.read_window_png(tile))

    return detect_window


class FakeDetectionService:
    def __init__(self) -> None:
        self.calls = 0

    async def detect(self, window_png: bytes) -> list[str]:
        self.calls += 1
        return [f"box in {window_png.decode()[:24]}"]

    async def recognize(
        self, crop_png: bytes, options: RecognizeOptions
    ) -> CropReading:
        self.calls += 1
        return CropReading(
            text=f"{options.language} reading of {crop_png.decode()}",
            confidence=0.97,
        )


def page_anchored_tile(window: Window) -> Window:
    """The page-anchored tile a selection falls in, not the selection itself.

    Anchoring to the page origin means a selection that moves by a few pixels stays
    in the same tile, so editing a selection over a TIFF that has not changed yields
    a hit. Anchoring to the selection would move all four bounds with the pointer and
    make every edit a fresh provider call.
    """

    return Window(
        page=window.page,
        x0=(window.x0 // TILE_PIXELS) * TILE_PIXELS,
        y0=(window.y0 // TILE_PIXELS) * TILE_PIXELS,
        x1=math.ceil(window.x1 / TILE_PIXELS) * TILE_PIXELS,
        y1=math.ceil(window.y1 / TILE_PIXELS) * TILE_PIXELS,
    )


def window_identity(source: FakeTiff, window: Window) -> JsonValue:
    """Everything that changes what a window read answers, and nothing else."""

    tile = page_anchored_tile(window)
    return {
        "tiff_sha256": source.sha256,
        "page": tile.page,
        "bounds": [tile.x0, tile.y0, tile.x1, tile.y1],
        "preprocessing": WINDOW_PREPROCESSING_VERSION,
        "detector": {"min_size": 6, "merge": True},
    }


def crop_identity(crop: PreparedCrop, options: RecognizeOptions) -> JsonValue:
    """The exact bytes being sent, plus the settings they are sent with."""

    return {
        "crop_sha256": hashlib.sha256(crop.png).hexdigest(),
        "preprocessing": CROP_PREPROCESSING_VERSION,
        "language": options.language,
        "preserve_layout": options.preserve_layout,
    }


def window_spec(ttl_seconds: int = 3_600) -> CacheSpec[list[str]]:
    return CacheSpec(
        operation="tiff.window_boxes",
        deployment="fake.detection@1",
        revision=WINDOW_REVISION,
        schema_version=1,
        codec=TypeAdapter(list[str]),
        ttl_seconds=ttl_seconds,
    )


def crop_spec(ttl_seconds: int = 3_600) -> CacheSpec[CropReading]:
    return CacheSpec(
        operation="ocr.recognize_crop",
        deployment="fake.recognizer@1",
        revision=RECOGNIZER_REVISION,
        schema_version=1,
        codec=TypeAdapter(CropReading),
        ttl_seconds=ttl_seconds,
    )


@pytest.fixture
def service() -> FakeDetectionService:
    return FakeDetectionService()


@pytest.fixture
def store() -> InMemoryCacheStore:
    return InMemoryCacheStore()


@pytest.fixture
def cache(store: InMemoryCacheStore) -> ProviderCache:
    return ProviderCache(store)


async def test_a_second_window_over_unchanged_bytes_neither_reads_nor_calls(
    cache: ProviderCache, store: InMemoryCacheStore, service: FakeDetectionService
) -> None:
    tiff = FakeTiff(b"one scanned page")
    detect_window = make_window_operation(service)

    wrapped = cached_call(
        detect_window,
        cache=cache,
        workspace=WORKSPACE,
        spec=window_spec(),
        identify=window_identity,
    )

    page_one = Window(page=0, x0=128, y0=128, x1=256, y1=256)
    hits: list[bool] = []
    again = cached_call(
        detect_window,
        cache=cache,
        workspace=WORKSPACE,
        spec=window_spec(),
        identify=window_identity,
        observe_hit=hits.append,
    )

    first = await wrapped(tiff, page_one)
    second = await again(tiff, page_one)

    assert second == first
    assert tiff.read_windows == [page_anchored_tile(page_one)]
    assert service.calls == 1
    assert hits == [True]
    assert store.entries == 1

    # A different page, or a re-uploaded file with different bytes, is a different
    # question and pays for itself.
    two_pages = FakeTiff(b"one scanned page", pages=2)
    await wrapped(two_pages, Window(page=1, x0=0, y0=0, x1=128, y1=128))
    changed = FakeTiff(b"one scanned page ")
    await wrapped(changed, page_one)
    assert service.calls == 3


async def test_a_selection_that_stays_in_its_page_tile_reuses_the_window(
    cache: ProviderCache, service: FakeDetectionService
) -> None:
    tiff = FakeTiff(b"aerial strip")
    detect_window = make_window_operation(service)

    wrapped = cached_call(
        detect_window,
        cache=cache,
        workspace=WORKSPACE,
        spec=window_spec(),
        identify=window_identity,
    )

    drawn = Window(page=0, x0=130, y0=133, x1=240, y1=250)
    nudged = Window(page=0, x0=133, y0=135, x1=248, y1=249)
    elsewhere = Window(page=0, x0=390, y0=130, x1=500, y1=250)

    assert await wrapped(tiff, nudged) == await wrapped(tiff, drawn)
    assert service.calls == 1
    # What left the file was the tile, once: the second selection changed nothing
    # about the question, so a caller that filters the boxes to its own selection
    # gets its edit answered without another provider call.
    assert tiff.read_windows == [page_anchored_tile(drawn)]
    assert page_anchored_tile(drawn) == page_anchored_tile(nudged)

    await wrapped(tiff, elsewhere)
    assert service.calls == 2


async def test_a_prepared_crop_is_reused_by_digest_whatever_it_came_from(
    cache: ProviderCache, service: FakeDetectionService
) -> None:
    async def recognize_crop(
        crop: PreparedCrop, options: RecognizeOptions
    ) -> CropReading:
        return await service.recognize(crop.png, options)

    wrapped = cached_call(
        recognize_crop,
        cache=cache,
        workspace=WORKSPACE,
        spec=crop_spec(),
        identify=crop_identity,
    )

    cut = PreparedCrop(png=b"crop-bytes", label="polygon 1")
    # The same pixels reached by another route: a polygon on a second page of a
    # second file. The key is the bytes that get sent, so the answer is shared.
    same_bytes_elsewhere = PreparedCrop(png=b"crop-bytes", label="polygon 9")
    other_language = RecognizeOptions(language="cs", preserve_layout=True)
    same_again = await wrapped(cut, other_language)
    assert await wrapped(same_bytes_elsewhere, other_language) == same_again
    assert service.calls == 1

    # A setting the provider would honour moves the key, in both directions.
    await wrapped(cut, RecognizeOptions(language="de", preserve_layout=True))
    await wrapped(cut, RecognizeOptions(language="cs", preserve_layout=False))
    assert service.calls == 3

    # Re-cutting the same region with a different normalisation is different input.
    await wrapped(
        PreparedCrop(png=b"crop-bytes-rescaled", label="polygon 1"), other_language
    )
    assert service.calls == 4


async def test_one_cache_serves_both_operation_shapes(
    cache: ProviderCache, store: InMemoryCacheStore, service: FakeDetectionService
) -> None:
    """The wrapper, the store and the workspace scope are shared; the specs are not."""

    tiff = FakeTiff(b"field survey scan")
    detect_window = make_window_operation(service)

    async def recognize_crop(
        crop: PreparedCrop, options: RecognizeOptions
    ) -> CropReading:
        return await service.recognize(crop.png, options)

    windows = cached_call(
        detect_window,
        cache=cache,
        workspace=WORKSPACE,
        spec=window_spec(),
        identify=window_identity,
    )
    crops = cached_call(
        recognize_crop,
        cache=cache,
        workspace=WORKSPACE,
        spec=crop_spec(),
        identify=crop_identity,
    )
    page_one = Window(page=0, x0=0, y0=0, x1=128, y1=128)
    options = RecognizeOptions(language="en", preserve_layout=False)

    assert await windows(tiff, page_one) == await windows(tiff, page_one)
    crop = PreparedCrop(png=b"crop-bytes", label="polygon 1")
    assert await crops(crop, options) == await crops(crop, options)

    assert service.calls == 2
    assert len(tiff.read_windows) == 1
    assert store.entries == 2
    assert window_spec().key(window_identity(tiff, page_one)) != crop_spec().key(
        crop_identity(crop, options)
    )


async def test_an_unwrapped_provider_never_sees_the_cache(
    cache: ProviderCache, store: InMemoryCacheStore, service: FakeDetectionService
) -> None:
    tiff = FakeTiff(b"unchanged scan")
    detect_window = make_window_operation(service)

    page = Window(page=0, x0=0, y0=0, x1=128, y1=128)
    await detect_window(tiff, page)
    assert store.entries == 0

    wrapped = cached_call(
        detect_window,
        cache=cache,
        workspace=WORKSPACE,
        spec=window_spec(),
        identify=window_identity,
    )
    await wrapped(tiff, page)
    await wrapped(tiff, page)

    # One provider call behind the wrapper, and the provider object itself is
    # untouched by it: no cache attribute, no extra argument, no awareness.
    assert service.calls == 2
    assert store.entries == 1
    assert not any("cache" in name.lower() for name in dir(service))


def test_the_wrapper_keeps_the_operation_signature() -> None:
    cache = ProviderCache(InMemoryCacheStore())

    async def recognize_crop(
        crop: PreparedCrop, options: RecognizeOptions, *, retries: int = 0
    ) -> CropReading:
        del crop, options, retries
        return CropReading(text="x", confidence=0.5)

    wrapped = cached_call(
        recognize_crop,
        cache=cache,
        workspace=WORKSPACE,
        spec=crop_spec(),
        identify=lambda crop, options, retries=0: {
            "crop_sha256": hashlib.sha256(crop.png).hexdigest(),
            "language": options.language,
            "retries": retries,
        },
    )
    assert inspect.signature(wrapped) == inspect.signature(recognize_crop)


async def test_a_lazy_window_read_happens_only_on_a_miss(
    cache: ProviderCache, service: FakeDetectionService
) -> None:
    """The explicit-request form, for an operation with no callable to wrap.

    A window read is a closure over bytes that have not been read yet, so the caller
    hands the work in rather than a signature to decorate. The identity it states is
    the same one the decorated form would have derived, which is why the two forms
    read each other's answers.
    """

    tiff = FakeTiff(b"map sheet")
    window = Window(page=0, x0=128, y0=0, x1=256, y1=128)
    request = window_identity(tiff, window)
    reads = 0

    async def read_and_detect() -> list[str]:
        nonlocal reads
        reads += 1
        tile = page_anchored_tile(window)
        return await service.detect(await tiff.read_window_png(tile))

    spec = window_spec()
    first, first_hit = await cache.get_or_compute(
        WORKSPACE, spec, request, read_and_detect
    )
    second, second_hit = await cache.get_or_compute(
        WORKSPACE, spec, request, read_and_detect
    )

    assert (first_hit, second_hit) == (False, True)
    assert second == first
    assert first[0].startswith("box in png-of-0:128,0,256,128")
    # Neither the TIFF read nor the provider call happened the second time, which is
    # the whole reason the window is wrapped before it is served rather than after.
    assert reads == 1
    assert len(tiff.read_windows) == 1
    assert service.calls == 1

    # The decorated form over the same bytes and window finds this answer too.
    detect_window = make_window_operation(service)
    wrapped = cached_call(
        detect_window,
        cache=cache,
        workspace=WORKSPACE,
        spec=window_spec(),
        identify=window_identity,
    )
    assert await wrapped(tiff, window) == first
    assert service.calls == 1

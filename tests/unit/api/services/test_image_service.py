from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl, SecretStr

from grafy_api.artifacts.images import (
    ArtifactImageService,
    ImageProxyError,
    ImageRead,
    TiffSource,
    TileExtension,
    TilerImage,
    TilerPort,
)
from grafy_api.artifacts.models import ImageInfoResponse
from grafy_core.artifacts import ArtifactObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_shared.config.tiler import TilerConfig

WS = UUID(int=1)
SOURCE = TiffSource(
    bucket="bucket",
    key="workspace/scan.tif",
    sha256="a" * 64,
    byte_size=100,
    page=2,
)
INFO = ImageInfoResponse(
    width=1024,
    height=512,
    page=0,
    page_count=1,
    band_count=1,
    dtype="uint8",
    bit_depth=8,
    kind="gray",
    has_alpha=False,
    tile_size=512,
    min_level=1,
    max_level=10,
    tile_format="jpg",
    resampling="average",
    overview_count=0,
    overview_level=None,
    value_range=None,
    palette=None,
    georeferenced=False,
    crs=None,
    bounds_wgs84=None,
)


class FakeTiler(TilerPort):
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.closed = False

    async def info(self, source: TiffSource) -> ImageInfoResponse:
        self.calls.append(("info", source))
        return INFO

    async def tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage:
        self.calls.append(("tile", source, z, x, y, extension))
        return TilerImage(b"tile", "image/jpeg")

    async def thumbnail(self, source: TiffSource, *, edge: int) -> TilerImage:
        self.calls.append(("thumbnail", source, edge))
        return TilerImage(b"thumb", "image/png")

    async def close(self) -> None:
        self.closed = True


class Harness:
    def __init__(
        self,
        service: ArtifactImageService,
        fake: FakeTiler,
        artifact: ArtifactObject,
        config: TilerConfig,
    ) -> None:
        self.service = service
        self.fake = fake
        self.artifact = artifact
        self.config = config


async def make_harness() -> Harness:
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=WS,
        artifact_type="file.tiff",
        schema_version=1,
        content_type="image/tiff",
        bucket="bucket",
        object_key="workspace/scan.tif",
        sha256="a" * 64,
        byte_size=100,
    )
    async with uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    config = TilerConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        tiler_url=HttpUrl("http://tiler:8100"),
        tiler_shared_key=SecretStr("test-key-" * 8),
    )
    fake = FakeTiler()
    return Harness(ArtifactImageService(uow, config, fake), fake, artifact, config)


async def test_tile_passes_the_typed_source_and_coordinates() -> None:
    harness = await make_harness()
    result = await harness.service.tile(
        WS,
        harness.artifact.id,
        z=3,
        x=2,
        y=1,
        extension="jpg",
        page=2,
        if_none_match=None,
    )
    assert isinstance(result, ImageRead)
    assert (result.body, result.content_type) == (b"tile", "image/jpeg")
    assert harness.fake.calls == [("tile", SOURCE, 3, 2, 1, "jpg")]


async def test_thumbnail_passes_edge() -> None:
    harness = await make_harness()
    result = await harness.service.thumbnail(
        WS, harness.artifact.id, edge=512, page=0, if_none_match=None
    )
    assert result.body == b"thumb"
    assert harness.fake.calls[0] == ("thumbnail", replace(SOURCE, page=0), 512)


async def test_info_serialises_the_descriptor() -> None:
    harness = await make_harness()
    result = await harness.service.info(
        WS, harness.artifact.id, page=0, if_none_match=None
    )
    assert result.content_type == "application/json"
    assert ImageInfoResponse.model_validate_json(result.body) == INFO


async def test_matching_etag_skips_the_tiler() -> None:
    harness = await make_harness()
    first = await harness.service.tile(
        WS,
        harness.artifact.id,
        z=3,
        x=2,
        y=1,
        extension="jpg",
        page=2,
        if_none_match=None,
    )
    second = await harness.service.tile(
        WS,
        harness.artifact.id,
        z=3,
        x=2,
        y=1,
        extension="jpg",
        page=2,
        if_none_match=first.etag,
    )
    assert second.not_modified is True
    assert second.body == b""
    assert second.etag == first.etag
    assert len(harness.fake.calls) == 1


async def test_missing_artifact_is_404_without_calling_the_tiler() -> None:
    harness = await make_harness()
    with pytest.raises(ImageProxyError) as exc_info:
        await harness.service.tile(
            WS,
            uuid4(),
            z=0,
            x=0,
            y=0,
            extension="jpg",
            page=0,
            if_none_match=None,
        )
    assert exc_info.value.status == 404
    assert harness.fake.calls == []


async def test_disabled_tiler_is_501_without_calling_the_tiler() -> None:
    harness = await make_harness()
    harness.config.tiler_url = None
    with pytest.raises(ImageProxyError) as exc_info:
        await harness.service.info(WS, harness.artifact.id, page=0, if_none_match=None)
    assert exc_info.value.status == 501
    assert harness.fake.calls == []


async def test_close_closes_the_tiler() -> None:
    harness = await make_harness()
    await harness.service.close()
    assert harness.fake.closed is True

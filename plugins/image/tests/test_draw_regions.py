from io import BytesIO
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from PIL import Image
from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    RASTER_IMAGE,
    ImagePage,
    ImageRegion,
    ImageRegionSet,
)
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.in_memory import InMemoryUnitOfWork

from grafy_plugin_image import IMAGES
from grafy_core.runtime.invocation import (
    InvocationError,
    InvocationMode,
    NodeInvocation,
    validate_invocation,
)

from grafy_plugin_image.nodes import (
    CropRegionsConfig,
    CropRegionsInput,
    CropRegionsNode,
    DrawRegionsConfig,
    DrawRegionsError,
    DrawRegionsInput,
    DrawRegionsNode,
    render_regions,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class FakeStorage:
    def __init__(self, content: bytes) -> None:
        self.stream = BytesIO(content)

    async def load(self, bucket: str, path: str) -> BytesIO:
        assert (bucket, path) == ("artifacts", "scan.png")
        return self.stream

    async def save(self, command: SaveFileCommand) -> StoredFile:
        raise AssertionError(f"Unexpected save to {command.path}")

    async def move(self, bucket: str, source_path: str, destination_path: str) -> None:
        raise AssertionError(
            f"Unexpected move in {bucket}: {source_path} to {destination_path}"
        )

    async def open_chunks(self, bucket: str, path: str) -> BytesIO:
        return await self.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        raise AssertionError(f"Unexpected stat for {bucket}/{path}")

    async def load_range(
        self, bucket: str, path: str, start: int, end_exclusive: int
    ) -> bytes:
        raise AssertionError(
            f"Unexpected range load for {bucket}/{path}: {start}:{end_exclusive}"
        )

    async def delete(self, bucket: str, path: str) -> None:
        raise AssertionError(f"Unexpected delete for {bucket}/{path}")


def region_set(kind: str = "table") -> ImageRegionSet:
    return ImageRegionSet(
        pages=[ImagePage(index=0, width=200, height=100)],
        regions=[ImageRegion(x0=20, y0=20, x1=60, y1=60, kind=kind)],
    )


def test_scales_outlines_and_preserves_unfilled_center() -> None:
    source = Image.new("RGB", (100, 50), "white")
    content = render_regions(
        source,
        region_set(),
        DrawRegionsConfig(
            fill_opacity=0,
            label_text="none",
            line_width=2,
        ),
    )
    with Image.open(BytesIO(content)) as output:
        assert output.format == "PNG"
        assert output.mode == "RGB"
        assert output.size == (100, 50)
        assert output.getpixel((10, 10)) == (34, 197, 94)
        assert output.getpixel((20, 20)) == (255, 255, 255)
    assert source.getpixel((10, 10)) == (255, 255, 255)


@pytest.mark.parametrize(
    "opacity, expected", [(1.0, (34, 197, 94)), (0.5, (144, 226, 174))]
)
def test_fill_opacity(opacity: float, expected: tuple[int, int, int]) -> None:
    content = render_regions(
        Image.new("RGB", (100, 50), "white"),
        region_set(),
        DrawRegionsConfig(fill_opacity=opacity, label_text="none"),
    )
    with Image.open(BytesIO(content)) as output:
        assert output.getpixel((20, 20)) == expected


def test_outside_boxes_are_skipped_and_partial_boxes_are_clamped() -> None:
    regions = ImageRegionSet(
        pages=[ImagePage(index=0, width=100, height=50)],
        regions=[
            ImageRegion(x0=100, y0=10, x1=120, y1=30, kind="title"),
            ImageRegion(x0=10, y0=50, x1=30, y1=70, kind="title"),
            ImageRegion(x0=90, y0=40, x1=120, y1=60, kind="table"),
        ],
    )
    content = render_regions(
        Image.new("RGB", (100, 50), "white"),
        regions,
        DrawRegionsConfig(fill_opacity=0, label_text="none", line_width=1),
    )
    with Image.open(BytesIO(content)) as output:
        assert output.getpixel((99, 10)) == (255, 255, 255)
        assert output.getpixel((10, 49)) == (255, 255, 255)
        assert output.getpixel((99, 45)) == (34, 197, 94)
        assert output.getpixel((95, 49)) == (34, 197, 94)


def test_unknown_kind_color_is_deterministic() -> None:
    image = Image.new("RGB", (100, 50), "white")
    config = DrawRegionsConfig(label_text="none")
    first = render_regions(image, region_set("custom"), config)
    assert first == render_regions(image, region_set("custom"), config)
    with Image.open(BytesIO(first)) as output:
        assert output.getpixel((10, 10)) == (20, 184, 166)


def test_rgba_input_keeps_alpha() -> None:
    content = render_regions(
        Image.new("RGBA", (100, 50), (255, 255, 255, 40)),
        region_set(),
        DrawRegionsConfig(label_text="none"),
    )
    with Image.open(BytesIO(content)) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((0, 0)) == (255, 255, 255, 40)


@pytest.mark.parametrize("label_text", ["kind", "label", "none"])
def test_labels_above_box_and_inside_at_top(
    label_text: Literal["kind", "label", "none"],
) -> None:
    regions = ImageRegionSet(
        pages=[ImagePage(index=0, width=200, height=100)],
        regions=[
            ImageRegion(x0=20, y0=60, x1=60, y1=90, kind="table", label="Long " * 20),
            ImageRegion(x0=100, y0=0, x1=180, y1=20, kind="table", label="Top"),
        ],
    )
    content = render_regions(
        Image.new("RGB", (200, 100), "white"),
        regions,
        DrawRegionsConfig(label_text=label_text, fill_opacity=0),
    )
    with Image.open(BytesIO(content)) as output:
        expected = (255, 255, 255) if label_text == "none" else (34, 197, 94)
        assert output.getpixel((20, 58)) == expected
        assert output.size == (200, 100)


async def test_node_loads_raster_and_preserves_filename() -> None:
    buffer = BytesIO()
    Image.new("RGB", (100, 50), "white").save(buffer, format="PNG")
    storage = FakeStorage(buffer.getvalue())
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        id=uuid4(),
        workspace_id=WORKSPACE_ID,
        artifact_type=RASTER_IMAGE.key.id,
        schema_version=1,
        content_type="image/png",
        bucket="artifacts",
        object_key="scan.png",
        metadata={"original_filename": "scan.png"},
    )
    async with uow as transaction:
        _ = await transaction.artifacts.add(artifact)
        _ = await transaction.commit()
    output = await DrawRegionsNode(storage=storage, uow=uow).run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="draw"),
        DrawRegionsConfig(label_text="none"),
        DrawRegionsInput(image=artifact.ref(), regions=region_set()),
    )
    assert output.image.filename == "scan-regions.png"
    assert output.image.content_type == "image/png"
    assert storage.stream.closed
    with Image.open(BytesIO(output.image.content)) as image:
        assert image.getpixel((10, 10)) == (34, 197, 94)


@pytest.mark.parametrize("wrong_type", [False, True])
async def test_node_rejects_missing_or_wrong_type_artifact(wrong_type: bool) -> None:
    ref = ArtifactRef.from_key(
        artifact_id=uuid4(), key=IMAGE_REGIONS.key if wrong_type else RASTER_IMAGE.key
    )
    with pytest.raises(DrawRegionsError, match=str(ref.artifact_id)):
        _ = await DrawRegionsNode(
            storage=FakeStorage(b""), uow=InMemoryUnitOfWork()
        ).run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID),
            DrawRegionsConfig(),
            DrawRegionsInput(image=ref, regions=region_set()),
        )


@pytest.mark.parametrize("stored", [False, True])
async def test_node_wraps_storage_and_decode_errors(stored: bool) -> None:
    uow = InMemoryUnitOfWork()
    storage = FakeStorage(b"invalid png")
    artifact = ArtifactObject(
        id=uuid4(),
        workspace_id=WORKSPACE_ID,
        artifact_type=RASTER_IMAGE.key.id,
        schema_version=1,
        content_type="image/png",
        bucket="artifacts",
        object_key="scan.png" if stored else "missing.png",
    )
    async with uow as transaction:
        _ = await transaction.artifacts.add(artifact)
        _ = await transaction.commit()
    with pytest.raises(DrawRegionsError, match=str(artifact.id)) as raised:
        _ = await DrawRegionsNode(storage=storage, uow=uow).run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID),
            DrawRegionsConfig(),
            DrawRegionsInput(image=artifact.ref(), regions=region_set()),
        )
    assert raised.value.__cause__ is not None
    assert storage.stream.closed == stored


def test_kinds_normalize_and_allow_free_form_values() -> None:
    assert DrawRegionsConfig().kinds is None
    assert DrawRegionsConfig(kinds="table, custom,table").kinds == "table,custom"


@pytest.mark.parametrize("kinds", ["", " ", "table,,title", "table,"])
def test_kinds_reject_empty_parts(kinds: str) -> None:
    with pytest.raises(
        ValidationError, match="kinds must be comma-separated region kinds"
    ):
        _ = DrawRegionsConfig(kinds=kinds)


def test_kind_filter_draws_only_matching_regions() -> None:
    regions = ImageRegionSet(
        pages=[ImagePage(index=0, width=100, height=50)],
        regions=[
            ImageRegion(x0=10, y0=10, x1=20, y1=20, kind="custom"),
            ImageRegion(x0=30, y0=10, x1=40, y1=20, kind="table"),
        ],
    )
    content = render_regions(
        Image.new("RGB", (100, 50), "white"),
        regions,
        DrawRegionsConfig(kinds="custom", label_text="none", fill_opacity=1),
    )
    with Image.open(BytesIO(content)) as output:
        assert output.getpixel((15, 15)) == (20, 184, 166)
        assert output.getpixel((35, 15)) == (255, 255, 255)


@pytest.mark.parametrize("map_input", ["image", "regions"])
def test_registered_draw_regions_contract_supports_map(map_input: str) -> None:
    registration = next(
        node for node in IMAGES.nodes if node.key == ("image.draw_regions", 1)
    )
    validate_invocation(
        registration.node_class,
        NodeInvocation(mode=InvocationMode.MAP, map_inputs=(map_input,)),
    )


@pytest.mark.parametrize("map_input", ["image", "regions"])
def test_registered_crop_regions_contract_rejects_map(map_input: str) -> None:
    registration = next(
        node for node in IMAGES.nodes if node.key == ("image.crop_regions", 1)
    )
    with pytest.raises(
        InvocationError, match="MAP output 'crops' must have shape 'one', got 'many'"
    ):
        validate_invocation(
            registration.node_class,
            NodeInvocation(mode=InvocationMode.MAP, map_inputs=(map_input,)),
        )


def test_draw_selects_page_and_uses_its_dimensions() -> None:
    regions = ImageRegionSet(
        pages=[
            ImagePage(index=0, width=100, height=50),
            ImagePage(index=3, width=200, height=100),
        ],
        regions=[
            ImageRegion(x0=60, y0=10, x1=80, y1=20, kind="title"),
            ImageRegion(page=3, x0=20, y0=20, x1=60, y1=60, kind="table"),
        ],
    )
    content = render_regions(
        Image.new("RGB", (100, 50), "white"),
        regions,
        DrawRegionsConfig(page=3, label_text="none", fill_opacity=1),
    )
    with Image.open(BytesIO(content)) as output:
        assert output.getpixel((15, 15)) == (34, 197, 94)
        assert output.getpixel((35, 7)) == (255, 255, 255)


def test_draw_rejects_missing_page_with_available_indexes() -> None:
    with pytest.raises(
        DrawRegionsError, match="Region set has no page 2; available pages: 0"
    ):
        _ = render_regions(
            Image.new("RGB", (100, 50)), region_set(), DrawRegionsConfig(page=2)
        )


@pytest.mark.parametrize(
    "mode, expected_mode",
    [("RGB", "RGB"), ("RGBA", "RGBA"), ("L", "RGB"), ("P", "RGBA"), ("LA", "RGBA")],
)
@pytest.mark.parametrize("filename", ["folder/scan.jpg", None])
async def test_crop_scales_filters_pads_clamps_and_preserves_mode(
    mode: str, expected_mode: str, filename: str | None
) -> None:
    source = Image.new(mode, (100, 50))
    if mode == "P":
        source.info["transparency"] = 0
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    storage = FakeStorage(buffer.getvalue())
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=RASTER_IMAGE.key.id,
        schema_version=1,
        content_type="image/png",
        bucket="artifacts",
        object_key="scan.png",
        metadata={"original_filename": filename},
    )
    async with uow as transaction:
        _ = await transaction.artifacts.add(artifact)
        _ = await transaction.commit()
    regions = ImageRegionSet(
        pages=[
            ImagePage(index=0, width=100, height=50),
            ImagePage(index=3, width=200, height=100),
        ],
        regions=[
            ImageRegion(x0=0, y0=0, x1=50, y1=50, kind="image"),
            ImageRegion(page=3, x0=20, y0=20, x1=60, y1=60, kind="image"),
            ImageRegion(page=3, x0=0, y0=0, x1=100, y1=100, kind="table"),
            ImageRegion(page=3, x0=180, y0=80, x1=240, y1=120, kind="image"),
            ImageRegion(page=3, x0=300, y0=0, x1=310, y1=20, kind="image"),
            ImageRegion(page=3, x0=40, y0=40, x1=40, y1=40, kind="image"),
        ],
    )
    output = await CropRegionsNode(storage=storage, uow=uow).run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="crop"),
        CropRegionsConfig(page=3, padding=2),
        CropRegionsInput(image=artifact.ref(), regions=regions),
    )
    stem = "scan" if filename else "region"
    assert [crop.filename for crop in output.crops] == [
        f"{stem}-image-{n}.png" for n in range(3)
    ]
    assert storage.stream.closed
    for crop, size in zip(output.crops, [(24, 24), (12, 12), (4, 4)], strict=True):
        assert crop.content_type == "image/png"
        with Image.open(BytesIO(crop.content)) as image:
            assert image.size == size
            assert image.mode == expected_mode
            assert image.getpixel((0, 0)) == source.convert(expected_mode).getpixel(
                (0, 0)
            )


async def test_crop_all_kinds_and_skips_zero_area_without_padding() -> None:
    buffer = BytesIO()
    Image.new("RGB", (100, 50), "red").save(buffer, format="PNG")
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=RASTER_IMAGE.key.id,
        schema_version=1,
        content_type="image/png",
        bucket="artifacts",
        object_key="scan.png",
    )
    async with uow as transaction:
        _ = await transaction.artifacts.add(artifact)
        _ = await transaction.commit()
    regions = region_set()
    regions.regions.append(ImageRegion(x0=20, y0=20, x1=20, y1=30, kind="image"))
    output = await CropRegionsNode(storage=FakeStorage(buffer.getvalue()), uow=uow).run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID),
        CropRegionsConfig(kinds=None),
        CropRegionsInput(image=artifact.ref(), regions=regions),
    )
    assert len(output.crops) == 1
    assert output.crops[0].filename == "region-table-0.png"


async def test_crop_rejects_missing_page_before_loading_image() -> None:
    with pytest.raises(
        DrawRegionsError, match="Region set has no page 2; available pages: 0"
    ):
        _ = await CropRegionsNode(
            storage=FakeStorage(b""), uow=InMemoryUnitOfWork()
        ).run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID),
            CropRegionsConfig(page=2),
            CropRegionsInput(
                image=ArtifactRef.from_key(artifact_id=uuid4(), key=RASTER_IMAGE.key),
                regions=region_set(),
            ),
        )


@pytest.mark.parametrize("config", [DrawRegionsConfig, CropRegionsConfig])
def test_region_config_validates_page_and_kinds(
    config: type[DrawRegionsConfig] | type[CropRegionsConfig],
) -> None:
    assert config(kinds="image, table,image").kinds == "image,table"
    with pytest.raises(ValidationError):
        _ = config(page=-1)
    with pytest.raises(ValidationError, match="kinds must be comma-separated"):
        _ = config(kinds="image,")

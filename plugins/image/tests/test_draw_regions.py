from io import BytesIO
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from PIL import Image
from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    RASTER_IMAGE,
    ImageRegion,
    ImageRegionSet,
)
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.in_memory import InMemoryUnitOfWork

from grafy_plugin_image.nodes import (
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
        width=200,
        height=100,
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
        width=100,
        height=50,
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
        width=200,
        height=100,
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
        width=100,
        height=50,
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

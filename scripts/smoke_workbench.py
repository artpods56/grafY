import asyncio
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageDraw

from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    RASTER_IMAGE,
    ImagePage,
    ImageRegion,
    ImageRegionSet,
)
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
)
from grafy_core.canonical_conversions import PNG_FILE_TO_RASTER
from grafy_core.documents import FILE_ARTIFACTS
from grafy_core.file_contracts import PNG_FILE
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.edge_transform import EdgeTransform
from grafy_core.runtime.execution import NodeRuntime, PersistedNodeOutput
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationProvenance,
)
from grafy_core.runtime.persistence import (
    ArtifactWriteContext,
    OutputPersister,
)
from grafy_storage import LocalFileObjectStore
from grafy_plugin_image import IMAGES as IMAGE_OPERATORS
from grafy_workbench.image import IMAGES


WORKSPACE = Path(".grafy-artifacts/workbench-smoke").resolve()
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")
SAMPLE_DIR = WORKSPACE / "samples"
OBJECT_STORE = WORKSPACE / "objects"
BUCKET = "workbench-artifacts"
IMAGE_SIZE = (260, 90)


async def main() -> None:
    image_paths = create_sample_images(SAMPLE_DIR / str(WORKSPACE_ID))

    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(OBJECT_STORE)
    plugin_registry = PluginRegistry()
    plugin_registry.install(IMAGES)
    plugin_registry.install(IMAGE_OPERATORS)
    plugin_registry.freeze()
    plugin_context = PluginRuntimeContext(
        workspace=WORKSPACE,
        storage=storage,
        uow=uow,
        bucket=BUCKET,
    )
    values = ArtifactValues(
        (*FILE_ARTIFACTS, *plugin_registry.artifacts),
        uow=uow,
        storage=storage,
        bucket=BUCKET,
        storage_backend="local",
    )
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )

    image_files = [
        await seed_file_artifact(
            storage,
            uow,
            content=path.read_bytes(),
            original_filename=path.name,
        )
        for path in image_paths
    ]
    regions_ref = await write_regions(values)

    # An image file reaches a raster port through its canonical conversion, the
    # same way a connection does: the stored file row is read, never retyped.
    crop_output = await runtime.run_node(
        plugin_registry.build_node("image.crop_regions", 1, plugin_context),
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="image_crop_1"),
        {
            "image": image_files[0],
            "regions": regions_ref,
        },
        transforms={
            "image": (
                EdgeTransform(
                    projection_path=None,
                    conversions=(PNG_FILE_TO_RASTER,),
                    delivered=RASTER_IMAGE.key,
                    label=f"{image_paths[0].name} image",
                ),
            ),
            "regions": (
                EdgeTransform(
                    projection_path=None,
                    conversions=(),
                    delivered=IMAGE_REGIONS.key,
                    label="boxes",
                ),
            ),
        },
    )
    crops = output_sequence(crop_output, "crops")

    async with uow as entered:
        image_artifacts = await entered.artifacts.list_by_type(
            WORKSPACE_ID,
            RASTER_IMAGE.key,
        )

    if len(image_artifacts) == 0:
        raise RuntimeError("Raster image writer did not persist an artifact")
    first_image = image_artifacts[0]
    if first_image.object_key is None:
        raise RuntimeError("Raster image writer did not persist a storage object")

    result: dict[str, object] = {
        "workspace": str(WORKSPACE),
        "cropped_sequence_id": crops.sequence_id,
        "raster_image_count": len(image_artifacts),
        "sequence_item_count": len(crops.item_refs),
        "first_cropped_ref": crops.item_refs[0].model_dump(mode="json"),
        "first_raster_object_key": first_image.object_key,
    }
    print(json.dumps(result, indent=2, default=str))


async def seed_file_artifact(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
    *,
    content: bytes,
    original_filename: str,
) -> ArtifactRef:
    """Persist the file.png artifact and bytes ingest would have written."""

    stored = await storage.save(
        SaveFileCommand(
            bucket=BUCKET,
            path=f"files/{PNG_FILE.key.id}/{sha256(content).hexdigest()}",
            stream=BytesIO(content),
            content_type="image/png",
            metadata={},
            allow_overwrite=True,
        )
    )
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=PNG_FILE.key.id,
        schema_version=PNG_FILE.key.schema_version,
        content_type="image/png",
        bucket=stored.bucket,
        object_key=stored.path,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        metadata={"original_filename": original_filename},
    )
    async with uow as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


async def write_regions(values: ArtifactValues) -> ArtifactRef:
    """Persist the boxes a document reader would have produced for page 0."""

    regions = ImageRegionSet(
        pages=[ImagePage(index=0, width=IMAGE_SIZE[0], height=IMAGE_SIZE[1])],
        regions=[
            ImageRegion(page=0, x0=10, y0=20, x1=140, y1=70, kind="image"),
        ],
    )
    return await values.write(
        IMAGE_REGIONS.key,
        regions,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="seed_regions",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )


def output_sequence(output: object, name: str) -> ArtifactRefSequence:
    if not isinstance(output, PersistedNodeOutput):
        raise RuntimeError(f"Node output is not persisted for {name!r}")
    value = output[name]
    if not isinstance(value, ArtifactRefSequence):
        raise RuntimeError(f"Output {name!r} is not an ArtifactRefSequence")
    return value


def create_sample_images(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / "page-001.png", directory / "page-002.png"]
    for index, path in enumerate(paths):
        image = Image.new("RGB", IMAGE_SIZE, color="white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 30), f"PAGE {index + 1}", fill="black")
        image.save(path, format="PNG")
    return paths


if __name__ == "__main__":
    _ = asyncio.run(main())

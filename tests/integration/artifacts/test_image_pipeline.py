from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from grafy_core.artifact_contracts import RASTER_IMAGE, RasterImageContent
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationProvenance,
)
from grafy_core.runtime.persistence import (
    ArtifactWriteContext,
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_plugin_ocr.artifacts import OCR_PAGE_RESULT
from grafy_plugin_ocr.persistence import OcrPageResultOutputWriter
from grafy_plugin_ocr.resolvers import PilImageResolver
from grafy_plugin_ocr.tesseract import FakeOcrEngine, TesseractOcrNode
from grafy_storage import LocalFileObjectStore
from grafy_workbench.image import IMAGES
from grafy_workbench.image.nodes import (
    ImageUploadError,
    RasterImageOutputWriter,
    UploadImagesNode,
)
from grafy_workbench.sequence.nodes import CollectNode
from PIL import Image

from tests.support.uploads import bundle_upload_reader, seed_ready_upload

TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def write_png(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(size))


def _png_bytes(size: tuple[int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_runtime_chains_image_collect_and_ocr_writers(tmp_path: Path) -> None:
    staging_root = tmp_path / "uploads"
    uow = InMemoryUnitOfWork()
    first_content = _png_bytes((3, 2))
    second_content = _png_bytes((5, 4))
    first_id = await seed_ready_upload(
        uow,
        uploads_dir=staging_root,
        workspace_id=TEST_WORKSPACE_ID,
        content=first_content,
        filename="page-001.png",
    )
    second_id = await seed_ready_upload(
        uow,
        uploads_dir=staging_root,
        workspace_id=TEST_WORKSPACE_ID,
        content=second_content,
        filename="page-002.png",
    )
    storage = LocalFileObjectStore(tmp_path / "object-store")
    runtime = NodeRuntime(
        materializer=InputMaterializer(
            ResolverRegistry([PilImageResolver(uow=uow, storage=storage)])
        ),
        persister=OutputPersister(
            ArtifactWriterRegistry(
                [
                    RasterImageOutputWriter(
                        storage=storage,
                        uow=uow,
                        bucket="artifacts",
                    ),
                    OcrPageResultOutputWriter(uow=uow, engine="fake"),
                ]
            )
        ),
    )

    upload_output = await runtime.run_node(
        UploadImagesNode(bundle_upload_reader(uow, uploads_dir=staging_root)),
        NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            node_id="image_upload_1",
        ),
        {},
        config={
            "uploads": [
                {
                    "upload_key": str(second_id),
                    "filename": "page-002.png",
                    "byte_size": len(second_content),
                },
                {
                    "upload_key": str(first_id),
                    "filename": "page-001.png",
                    "byte_size": len(first_content),
                },
            ],
        },
    )
    assert isinstance(upload_output, PersistedNodeOutput)
    uploaded_images = upload_output["images"]

    assert isinstance(uploaded_images, ArtifactRefSequence)
    assert uploaded_images.artifact_type == RASTER_IMAGE.key.id
    assert len(uploaded_images.item_refs) == 2

    collect_output = await runtime.run_node(
        CollectNode(),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collect_1"),
        {"items": [uploaded_images]},
        artifact_type_bindings={"T": RASTER_IMAGE.key},
    )
    assert isinstance(collect_output, PersistedNodeOutput)
    collected_images = collect_output["items"]

    assert isinstance(collected_images, ArtifactRefSequence)
    assert collected_images.item_refs == uploaded_images.item_refs
    assert collected_images.metadata["collect_segments"] == [
        {
            "input_index": 0,
            "start_index": 0,
            "item_count": 2,
            "source_kind": "sequence",
        }
    ]

    ocr_output = await runtime.run_node(
        TesseractOcrNode(FakeOcrEngine()),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="ocr_1"),
        {"pages": collected_images},
    )
    assert isinstance(ocr_output, PersistedNodeOutput)
    ocr_results = ocr_output["results"]

    assert isinstance(ocr_results, ArtifactRefSequence)
    assert ocr_results.artifact_type == OCR_PAGE_RESULT.key.id
    assert len(ocr_results.item_refs) == 2

    async with uow as entered:
        image_artifacts = await entered.artifacts.list_by_type(
            TEST_WORKSPACE_ID,
            RASTER_IMAGE.key,
        )
        ocr_artifacts = await entered.artifacts.list_by_type(
            TEST_WORKSPACE_ID,
            OCR_PAGE_RESULT.key,
        )

    assert [artifact.metadata["original_filename"] for artifact in image_artifacts] == [
        "page-002.png",
        "page-001.png",
    ]
    assert all(artifact.bucket == "artifacts" for artifact in image_artifacts)
    assert all(artifact.object_key is not None for artifact in image_artifacts)
    assert all(
        artifact.object_key is not None
        and artifact.object_key.startswith(
            f"workspaces/{TEST_WORKSPACE_ID}/image.raster/v1/"
        )
        for artifact in image_artifacts
    )
    assert all(
        artifact.workspace_id == TEST_WORKSPACE_ID for artifact in image_artifacts
    )
    assert all("upload_key" not in artifact.metadata for artifact in image_artifacts)
    texts: list[object] = []
    for artifact in ocr_artifacts:
        assert artifact.inline_payload is not None
        texts.append(artifact.inline_payload["text"])

    assert texts == ["fake OCR image 5x4", "fake OCR image 3x2"]


@pytest.mark.asyncio
async def test_ocr_many_input_requires_artifact_ref_sequence() -> None:
    page_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=RASTER_IMAGE.key,
    )
    materializer = InputMaterializer(ResolverRegistry())

    with pytest.raises(RuntimeError, match="wrap refs in an ArtifactRefSequence"):
        await materializer.materialize(
            TesseractOcrNode.input_contract,
            {"pages": [page_ref]},
            TEST_WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_upload_rejects_keys_that_are_not_upload_identifiers(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    node = UploadImagesNode(
        bundle_upload_reader(InMemoryUnitOfWork(), uploads_dir=uploads_dir)
    )

    with pytest.raises(ImageUploadError, match="not a known upload identifier"):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
            node.config_contract.model.model_validate(
                {
                    "uploads": [
                        {
                            "upload_key": "../outside.png",
                            "filename": "outside.png",
                            "byte_size": 1,
                        }
                    ]
                }
            ),
            node.input_contract.model.model_validate({}),
        )


@pytest.mark.asyncio
async def test_upload_fails_closed_when_file_exists_without_db_row(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    absent_id = uuid4()
    staged = uploads_dir / str(TEST_WORKSPACE_ID) / str(absent_id)
    staged.parent.mkdir(parents=True)
    write_png(staged, (2, 2))
    node = UploadImagesNode(
        bundle_upload_reader(InMemoryUnitOfWork(), uploads_dir=uploads_dir)
    )

    with pytest.raises(ImageUploadError, match="was not found in workspace"):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
            node.config_contract.model.model_validate(
                {
                    "uploads": [
                        {
                            "upload_key": str(absent_id),
                            "filename": "page.png",
                            "byte_size": staged.stat().st_size,
                        }
                    ]
                }
            ),
            node.input_contract.model.model_validate({}),
        )


@pytest.mark.asyncio
async def test_upload_fails_closed_for_row_in_another_workspace(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    other_workspace = UUID("00000000-0000-0000-0000-000000000902")
    content = _png_bytes((2, 2))
    uow = InMemoryUnitOfWork()
    foreign_id = await seed_ready_upload(
        uow,
        uploads_dir=uploads_dir,
        workspace_id=other_workspace,
        content=content,
        filename="page.png",
    )
    node = UploadImagesNode(bundle_upload_reader(uow, uploads_dir=uploads_dir))

    with pytest.raises(ImageUploadError, match="was not found in workspace"):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
            node.config_contract.model.model_validate(
                {
                    "uploads": [
                        {
                            "upload_key": str(foreign_id),
                            "filename": "page.png",
                            "byte_size": len(content),
                        }
                    ]
                }
            ),
            node.input_contract.model.model_validate({}),
        )


@pytest.mark.asyncio
async def test_raster_writer_persists_content_without_upload_metadata(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "generated.png"
    write_png(image_path, (2, 2))
    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    writer = RasterImageOutputWriter(
        storage=storage,
        uow=uow,
        bucket="artifacts",
    )

    ref = await writer.write(
        RasterImageContent(
            content=image_path.read_bytes(),
            content_type="image/png",
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="generated_image",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )

    assert ref.key() == RASTER_IMAGE.key
    async with uow as entered:
        artifact = await entered.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.metadata["producer_node_id"] == "generated_image"
    assert artifact.metadata["original_filename"] is None
    assert artifact.object_key is not None
    assert artifact.object_key.startswith(
        f"workspaces/{TEST_WORKSPACE_ID}/image.raster/v1/"
    )


def test_image_plugin_owns_the_raster_type_and_writer(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.install(IMAGES)
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    assert registry.artifact_types == (RASTER_IMAGE,)
    writers = registry.build_writers(context)
    assert len(writers) == 1
    assert writers[0].artifact_type == RASTER_IMAGE.key

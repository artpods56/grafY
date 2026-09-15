from pathlib import Path

import tomllib
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_plugin_ocr import OCR
from grafy_plugin_ocr.artifacts import OCR_PAGE_RESULT
from grafy_plugin_ocr.resolvers import PilImageResolver
from grafy_storage import LocalFileObjectStore
from grafy_workbench.image import IMAGES


def test_ocr_plugin_declares_complete_runtime_contributions(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.install(IMAGES)
    registry.install(OCR)
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    assert OCR.slug == "external.ocr"
    assert OCR.title == "OCR"
    registry.freeze()

    assert [(plugin.slug, plugin.title) for plugin in registry.plugins] == [
        (IMAGES.slug, IMAGES.title),
        (OCR.slug, OCR.title),
    ]
    ocr_registrations = [
        registration
        for registration in registry.nodes
        if registration.node_class.plugin_slug == OCR.slug
    ]
    assert {registration.key for registration in ocr_registrations} == {
        ("ocr.tesseract.pages", 2),
    }
    assert {
        registration.node_class.plugin_slug for registration in ocr_registrations
    } == {"external.ocr"}
    assert {registration.node_class.title for registration in ocr_registrations} == {
        "Tesseract OCR",
    }
    assert [artifact_type.key for artifact_type in registry.artifact_types] == [
        RASTER_IMAGE.key,
        OCR_PAGE_RESULT.key,
    ]
    assert [
        registry.build_node(*registration.key, context).__class__
        for registration in ocr_registrations
    ] == [registration.node_class for registration in ocr_registrations]

    resolvers = registry.build_resolvers(context)
    writers = registry.build_writers(context)

    assert len(resolvers) == 1
    assert {
        resolver.source
        for resolver in resolvers
        if isinstance(resolver, PilImageResolver)
    } == {RASTER_IMAGE.key}
    assert len(writers) == 2
    assert {writer.artifact_type for writer in writers} == {
        RASTER_IMAGE.key,
        OCR_PAGE_RESULT.key,
    }


def test_ocr_package_metadata_has_no_ambient_plugin_entry_point() -> None:
    project_root = Path(__file__).parents[3]
    metadata = tomllib.loads(
        (project_root / "plugins" / "ocr" / "pyproject.toml").read_text()
    )

    assert metadata["project"]["name"] == "grafy-plugin-ocr"
    assert "entry-points" not in metadata["project"]

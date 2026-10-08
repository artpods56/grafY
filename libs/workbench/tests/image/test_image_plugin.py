from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.plugins import PluginRegistry
from grafy_workbench.image.plugin import IMAGES


def test_image_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(IMAGES)
    registry.freeze()

    assert IMAGES.slug == "image"
    assert {artifact.key for artifact in IMAGES.artifact_types} == {RASTER_IMAGE.key}
    assert RASTER_IMAGE.bundle.format == "binary-file"
    assert RASTER_IMAGE.bundle.version == 1
    assert IMAGES.nodes == ()

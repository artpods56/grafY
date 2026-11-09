from importlib.metadata import requires

from grafy_core.artifact_contracts import IMAGE_REGIONS
from grafy_core.plugins import PluginRegistry
from grafy_plugin_image import IMAGES


def test_plugin_declares_image_operators() -> None:
    registry = PluginRegistry()
    registry.install(IMAGES)
    registry.freeze()

    assert IMAGES.slug == "external.image"
    assert {node.key for node in registry.nodes} == {
        ("image.decode", 1),
        ("image.crop_regions", 1),
        ("image.draw_regions", 1),
    }
    assert {
        (spec.key.id, spec.key.schema_version) for spec in IMAGES.artifact_types
    } == {(IMAGE_REGIONS.key.id, IMAGE_REGIONS.key.schema_version)}
    assert IMAGES.artifact_conversions == ()
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-image") or [])
    assert "pillow" in (requires("grafy-plugin-image") or [])

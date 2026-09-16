from importlib.metadata import requires

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin_gis.plugin import GIS


def test_manifest_loader_target_preserves_system_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(GIS)
    registry.freeze()

    assert isinstance(GIS, Plugin)
    assert GIS.slug == "external.gis"
    assert {registration.key for registration in GIS.nodes} == {
        ("gis.features.to_table", 1),
        ("gis.table.to_features", 1),
        ("gis.geojson.parse", 1),
        ("gis.geojson.upload", 1),
        ("gis.geotiff.upload", 1),
        ("gis.raster_scan.import", 1),
        ("gis.wfs.import", 1),
        ("gis.map.vector_layer", 1),
        ("gis.map.raster_layer", 1),
        ("gis.map.wms_layer", 1),
        ("gis.map.compose", 1),
    }
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-gis") or [])

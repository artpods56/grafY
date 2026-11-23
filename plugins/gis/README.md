# Grafy GIS family

Installed application family for GIS imports, layers, and map documents. Its
stable identifier is `external.gis`.

Install the Python workspace with `uv sync`. The GIS family uses stored TIFFs
directly in map layers. The tiler renders their map tiles on demand.

Run `uv run pytest tests/unit/plugins/test_gis_plugin.py` from the repository
root to check the raster and vector contracts.
See [the GIS smoke procedure](../../docs/how-to-run-gis.md) for the application
and artifact-viewing checks.

# Grafy GIS family

Installed application family for GIS imports, layers, and map documents. Its
stable identifier is `external.gis`.

Install the Python workspace with `uv sync`. Local execution also needs GDAL
3.8 or newer with writable PMTiles, COG, and PNG drivers, plus `gdal2tiles.py`.
The API image supplies these tools. GDAL runs in bounded subprocesses; it does
not need a Plugin image, a registry, or a Docker socket.

Run `uv run python -m grafy_plugin_gis.smoke` to check the native raster path.
See [the GIS smoke procedure](../../docs/how-to-run-gis.md) for the application
and artifact-viewing checks.

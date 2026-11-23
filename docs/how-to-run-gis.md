# View an uploaded TIFF on a map

1. Start Grafy with the tiler enabled. For native development, follow
   [the local setup](how-to-run-local.md).
2. Upload a georeferenced TIFF to the Library in your Workspace.
3. Open the TIFF and select **Show map**. Confirm the map frames the raster and
   the tile requests succeed. The tiler renders from the uploaded file.
4. To use the TIFF in a Graph, connect the `file.tiff` artifact directly to
   **Raster map layer** and connect that layer to **Compose map**. Run the
   Graph and open the resulting map.
5. To join several sheets, connect them to **Raster mosaic layer** in
   bottom-to-top order. Check the overlap and transparent edges.

The retired **Import raster scan** operator produces no artifact any more, so a
saved Graph that used it fails with an unknown operator until its raster is
reconnected: wire the uploaded `file.tiff` straight into the layer that consumed
the scan. Artifacts a past run produced stay in the Library and download
normally; opening one as a map does not work, because its stored tile pyramid is
no longer read.

Run `uv run pytest tests/unit/plugins/test_gis_plugin.py` to check the GIS
artifact and node contracts.

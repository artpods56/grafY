# Run and verify a GIS raster import

Use this procedure after the static application registry and web changes from
ADR 0017 are integrated. Python and SQL nodes stay unavailable.

## Check native execution

Install GDAL 3.8 or newer with `gdalinfo`, `gdal_create`, `gdal_translate`,
`ogr2ogr`, and `gdal2tiles.py`. The tools must support writable PMTiles, COG,
and PNG drivers. On Linux, `gdal2tiles.py` needs system Python bindings, NumPy,
and Pillow. The API image supplies them.

From the repository root, run:

```bash
uv sync
uv run python -m grafy_plugin_gis.smoke
```

The command creates a small GeoTIFF, persists it as a COG with XYZ tiles,
and resolves the stored artifact. It needs no API, OIDC session, or Docker.
It does not prove browser viewing, PostgreSQL persistence, or API registration.

To check the production image without starting a server:

```bash
digest="$(git archive HEAD | shasum -a 256 | cut -d ' ' -f 1)"
docker build --file infra/docker/api.Dockerfile --target api-release \
	--build-arg GRAFY_BUILD_DIGEST="$digest" --tag grafy-api:gis-check .
docker run --rm --network=none --entrypoint .venv/bin/python \
	grafy-api:gis-check -m grafy_plugin_gis.smoke
```

The release target requires the source archive digest. Build from a clean
checkout so that digest identifies the source copied into the image.

## Import and view a raster

1. Use a dedicated local data root and disposable database, with the normal
   local OIDC and secret settings. If an API already owns that root, use it.
   Do not start a second owner or use production `/etc/grafy` files.
2. Start the integrated API with `just api-dev` and the web app with `just web`.
   These commands use the installed application families. No Plugin runtime,
   registry, publication, or promotion step is needed.
3. Sign in and create a graph in your Workspace. Confirm **Import raster scan**
   is available and Python and SQL nodes are absent.
4. Upload a small georeferenced `.tif` to the Library. Select the resulting
   `file.tiff` artifact as the **file** input of **Import raster scan**
   (`gis.raster_scan.import`). Set its source name and execute it.
5. Open the resulting `geo.raster_scan` artifact. Confirm its map displays
   precomputed raster tiles and its metadata reports the expected bounds and
   CRS. Check that the browser's TileJSON and PNG requests succeed.
6. Add **Raster map layer** (`gis.map.raster_layer`) and **Compose map**
   (`gis.map.compose`), connect the raster through the layer to the map, and
   execute. Open the map artifact and confirm the raster is visible.
7. Run the unchanged import again. Confirm a cache hit. Change the source name
   and confirm a new execution. A different deployment digest also forces a
   new execution; it leaves historical artifacts and graph checkpoints intact.
8. Cancel a larger import during GDAL work. Confirm cancellation completes,
   then run the small import again to verify native capacity was released.

## Native execution limits

The helper admits two children per API process. Each child has a 1 GiB address
space limit on Linux, 300 CPU seconds, a 600-second wall limit, a 1 GiB limit
per output file, and 256 open files. It captures at most 1 MiB per output
stream. GDAL uses one native thread and a 64 MiB cache. Account for both children
and the API itself when sizing the deployment; the address-space limit is not
a container-wide memory quota. macOS does not enforce the address-space limit.

Cancellation kills the spawned process group and waits for child exit and pipe
cleanup before returning the concurrency slot. Children receive an explicit GDAL
environment rather than API credentials or the user's home configuration.

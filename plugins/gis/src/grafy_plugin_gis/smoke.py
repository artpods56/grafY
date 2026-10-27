"""Exercise the installed GIS family and its real native tools without an API."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from grafy_core.bounded_subprocess import run, run_in_thread
from grafy_core.nodes import NodeExecutionContext
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_plugin_gis.gdal import GdalCli
from grafy_plugin_gis.models import GeoRasterScan, RasterProjectionMetadata
from grafy_plugin_gis.persistence import RasterScanOutputWriter, RasterScanResolver
from grafy_storage import LocalFileObjectStore


async def main() -> None:
    gdal = GdalCli()
    capabilities = await run_in_thread(gdal.capabilities)
    if not (
        capabilities.pmtiles_write and capabilities.cog_write and capabilities.png_write
    ):
        raise RuntimeError(f"Missing writable GIS drivers: {capabilities}")
    with TemporaryDirectory(prefix="grafy-native-smoke-") as directory:
        root = Path(directory)
        source = root / "source.tif"
        await run_in_thread(
            run,
            [
                "gdal_create",
                "-of",
                "GTiff",
                "-outsize",
                "64",
                "64",
                "-bands",
                "3",
                "-burn",
                "100",
                "-burn",
                "150",
                "-burn",
                "200",
                "-a_srs",
                "EPSG:4326",
                "-a_ullr",
                "13",
                "53",
                "14",
                "52",
                str(source),
            ],
            operation="creating smoke raster",
            env={
                "PATH": os.environ.get("PATH", os.defpath),
                "GDAL_CONFIG_FILE": os.devnull,
            },
        )
        workspace_id = uuid4()
        uow = InMemoryUnitOfWork()
        storage = LocalFileObjectStore(root / "objects")
        writer = RasterScanOutputWriter(
            storage=storage,
            uow=uow,
            bucket="smoke",
            storage_backend="local",
            gdal=gdal,
        )
        ref = await writer.write(
            GeoRasterScan(
                content=source.read_bytes(),
                filename="source.tif",
                source_name="Native smoke",
            ),
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=workspace_id, node_id="raster"
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
        async with uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        assert artifact is not None and artifact.object_key is not None
        projection = RasterProjectionMetadata.model_validate(
            artifact.metadata["raster_projection"]
        )
        assert projection.bounds == (13.0, 52.0, 14.0, 53.0)
        assert list((root / "objects" / "smoke" / projection.prefix).rglob("*.png"))
        resolved = await RasterScanResolver(storage=storage, uow=uow).resolve(
            ref, workspace_id
        )
        assert resolved.filename == "source.tif" and resolved.content
        print(capabilities.model_dump_json())
        print("GIS raster persisted as COG, XYZ tiles stored, artifact resolved")


if __name__ == "__main__":
    asyncio.run(main())

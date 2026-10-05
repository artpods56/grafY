import asyncio
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.services.errors import ArtifactContentUnavailableError
from grafy_api.v1.routes.artifacts.models import GeoRasterStyle
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_core.artifacts import ArtifactObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore


@pytest.mark.parametrize("view", ["render", "tilejson", "tile"])
@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://100.64.0.1/wms", "WMS URL must not target"),
        ("https://maps.example.com/wms?service=WMS", "query-free service endpoint"),
    ],
)
async def test_stored_wms_layer_rejects_unsafe_endpoint_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    view: Literal["render", "tilejson", "tile"],
    url: str,
    message: str,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path)
    service = ArtifactService(
        unit_of_work,
        storage,
        availability=ArtifactAvailability(unit_of_work, storage),
    )
    artifact = ArtifactObject(
        workspace_id=UUID("00000000-0000-0000-0000-000000000007"),
        artifact_type="geo.map_layer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={
            "title": "Stored WMS",
            "visible": True,
            "opacity": 1.0,
            "min_zoom": 0,
            "max_zoom": 22,
            "source": {
                "kind": "wms",
                "url": url,
                "layer": "public:layer",
                "version": "1.3.0",
                "format": "image/png",
                "bounds": [-180.0, -85.0, 180.0, 85.0],
                "attribution": "Public maps",
            },
            "style": GeoRasterStyle.default().model_dump(mode="json"),
        },
    )
    dns = AsyncMock(side_effect=AssertionError("Rejected WMS must not resolve DNS"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    try:
        async with unit_of_work:
            await unit_of_work.artifacts.add(artifact)
            await unit_of_work.commit()
        stored = await service.get(artifact.workspace_id, artifact.id)
        assert stored is not None

        expected_error = (
            ValueError if view == "tilejson" else ArtifactContentUnavailableError
        )
        with pytest.raises(expected_error) as error:
            if view == "render":
                _ = await service.load_geo_render(stored, workspace_id=stored.workspace_id)
            elif view == "tilejson":
                _ = await service.load_raster_tilejson(
                    stored, workspace_id=stored.workspace_id
                )
            else:
                _ = await service.load_raster_tile(
                    stored, workspace_id=stored.workspace_id, z=0, x=0, y=0
                )

        dns.assert_not_awaited()
        cause = error.value if view == "tilejson" else error.value.__cause__
        assert isinstance(cause, ValueError)
        assert message in str(cause)
        if view != "tilejson":
            assert str(stored.id) in str(error.value)
    finally:
        await service.close()

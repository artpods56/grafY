from pathlib import Path
import socket
from uuid import UUID

import pytest

from grafy_api.services.errors import ArtifactContentUnavailableError
from grafy_api.services.composition import build_workbench_components
from grafy_api.v1.routes.artifacts.models import GeoRasterStyle
from grafy_core.artifacts import ArtifactObject
from grafy_core.plugins import PluginRuntimeContext
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore
from grafy_workbench.value.nodes import (
    INTEGER_VALUE,
    IntegerValueOutputWriter,
    IntegerValueResolver,
)
from grafy_workbench.text.nodes import (
    TEXT_VALUE,
    TextValueOutputWriter,
    TextValueResolver,
)

from tests.support.egress import (
    loopback_http_listener,
    no_grants,
    resolve_loopback_host,
    trusted_loopback_network,
)
from tests.support.system_plugins import build_explicit_plugin_registry


def test_builtin_scalar_runtime_contributions_come_from_plugin_registry(
    tmp_path: Path,
) -> None:
    registry = build_explicit_plugin_registry()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    resolvers = {
        resolver.source: resolver for resolver in registry.build_resolvers(context)
    }
    writers = {
        writer.artifact_type: writer for writer in registry.build_writers(context)
    }

    assert isinstance(resolvers[INTEGER_VALUE.key], IntegerValueResolver)
    assert isinstance(writers[INTEGER_VALUE.key], IntegerValueOutputWriter)
    assert isinstance(resolvers[TEXT_VALUE.key], TextValueResolver)
    assert isinstance(writers[TEXT_VALUE.key], TextValueOutputWriter)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")


def _wms_layer_artifact(url: str) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="geo.map_layer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={
            "title": "Internal WMS",
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
                "attribution": "Internal maps",
            },
            "style": GeoRasterStyle.default().model_dump(mode="json"),
        },
    )


async def test_composition_hands_the_egress_policy_to_the_component_that_dials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy is composed once and the workbench dials with it.

    The WMS tile reader is the component that dials inside a workbench, so the
    grant given to `build_workbench_components` is what decides whether an author's
    destination is reached. Without it the same composition refuses the same tile.
    """

    monkeypatch.setattr(socket, "getaddrinfo", resolve_loopback_host)

    async def fetch_tile(egress_policy: object) -> bytes:
        unit_of_work = InMemoryUnitOfWork()
        storage = LocalFileObjectStore(tmp_path / f"objects-{id(egress_policy)}")
        components = build_workbench_components(
            plugin_registry=build_explicit_plugin_registry(),
            workspace=tmp_path,
            unit_of_work=unit_of_work,
            storage=storage,
            egress_policy=egress_policy,  # pyright: ignore[reportArgumentType]
        )
        try:
            async with unit_of_work:
                await unit_of_work.artifacts.add(artifact)
                await unit_of_work.commit()
            stored = await components.artifacts.get(artifact.workspace_id, artifact.id)
            assert stored is not None
            read = await components.artifacts.load_raster_tile(
                stored,
                workspace_id=stored.workspace_id,
                z=0,
                x=0,
                y=0,
            )
            return read.content
        finally:
            await components.artifacts.close()

    async with loopback_http_listener(
        body=b"png-tile",
        content_type="image/png",
    ) as listener:
        artifact = _wms_layer_artifact(f"http://maps.internal:{listener.port}/wms")

        assert await fetch_tile(trusted_loopback_network()) == b"png-tile"
        assert listener.requests[0].headers["host"] == f"maps.internal:{listener.port}"

        with pytest.raises(ArtifactContentUnavailableError):
            await fetch_tile(no_grants())

        assert len(listener.requests) == 1

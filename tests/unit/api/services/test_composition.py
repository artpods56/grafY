from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, StrictInt

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, JsonObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_workbench.arithmetic.nodes import (
    INTEGER_VALUE,
    IntegerValueOutputWriter,
    IntegerValueResolver,
)
from grafy_workbench.text.nodes import (
    TEXT_VALUE,
    TextValueOutputWriter,
    TextValueResolver,
)
from grafy_core.plugins import Plugin, PluginRuntimeContext
from grafy_core.runtime.resolvers import InlineModelResolver
from grafy_storage import LocalFileObjectStore

from grafy_api.services.composition import build_workbench_components
from tests.support.system_plugins import (
    TEST_SYSTEM_PLUGINS,
    build_explicit_plugin_registry,
)


class CompositionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictInt


COMPOSITION_ARTIFACT = ArtifactTypeSpec(
    key=ArtifactTypeKey("test.composition", 1),
    title="Composition test",
    payload_schema=cast(JsonObject, CompositionPayload.model_json_schema()),
)


def test_builtin_scalar_runtime_contributions_come_from_plugin_registry(
    tmp_path: Path,
) -> None:
    registry = build_explicit_plugin_registry()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
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


def test_plugin_factories_receive_an_existing_upload_directory(tmp_path: Path) -> None:
    observed_upload_directories: list[Path] = []
    plugin = Plugin(slug="test.composition", title="Composition test")
    plugin.register_artifact_type(COMPOSITION_ARTIFACT)

    def resolver_factory(
        context: PluginRuntimeContext,
    ) -> InlineModelResolver[CompositionPayload]:
        assert context.uploads_dir.is_dir()
        observed_upload_directories.append(context.uploads_dir)
        return InlineModelResolver(
            source=COMPOSITION_ARTIFACT.key,
            target=CompositionPayload,
            uow=context.uow,
        )

    plugin.register_resolver(resolver_factory)
    registry = build_explicit_plugin_registry(
        (*TEST_SYSTEM_PLUGINS, plugin),
    )

    build_workbench_components(
        plugin_registry=registry,
        workspace=tmp_path / "workbench",
    )

    assert observed_upload_directories == [
        (tmp_path / "workbench" / "uploads").resolve()
    ]

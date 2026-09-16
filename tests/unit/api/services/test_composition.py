from pathlib import Path

from grafy_core.plugins import PluginRuntimeContext
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore
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

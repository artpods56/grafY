"""Supported artifact imports must work independently of import order."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "first_module",
    [
        "grafy_core.artifacts",
        "grafy_core.domain.modules",
        "grafy_core.ports.artifacts",
        "grafy_core.runtime.in_memory",
        "grafy_core.plugins",
    ],
)
def test_artifact_models_resolve_independently_of_import_order(
    first_module: str,
) -> None:
    source = f"""
from importlib import import_module
import_module({first_module!r})
from grafy_core import artifacts
namespace = {{}}
exec('from grafy_core.artifacts import *', namespace)
for name in artifacts.__all__:
    assert namespace[name] is getattr(artifacts, name)
try:
    artifacts.unknown_export
except AttributeError:
    pass
else:
    raise AssertionError('Unknown exports must raise AttributeError')
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "ArtifactRepositoryPort",
        "UnitOfWorkPort",
        "InMemoryArtifactRepository",
        "InMemoryDataStore",
        "InMemoryGraphExecutionHistoryRepository",
        "InMemoryInvocationCacheRepository",
        "InMemoryMaterializedNodeOutputsRepository",
        "InMemoryUnitOfWork",
        "InMemoryUploadRepository",
    ],
)
def test_artifact_module_no_longer_exports_owned_names(name: str) -> None:
    """Ports and in-memory fakes are imported from the modules that own them."""

    from grafy_core import artifacts

    assert name not in artifacts.__all__
    with pytest.raises(AttributeError, match=name):
        getattr(artifacts, name)

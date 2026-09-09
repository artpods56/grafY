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
def test_artifact_sdk_exports_resolve_to_their_owners(first_module: str) -> None:
    source = f"""
from importlib import import_module
import_module({first_module!r})
from grafy_core import artifacts
from grafy_core.ports.artifacts import ArtifactRepositoryPort, UnitOfWorkPort
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
assert artifacts.ArtifactRepositoryPort is ArtifactRepositoryPort
assert artifacts.UnitOfWorkPort is UnitOfWorkPort
assert artifacts.InMemoryDataStore is InMemoryDataStore
assert artifacts.InMemoryUnitOfWork is InMemoryUnitOfWork
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

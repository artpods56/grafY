from typing import cast

import pytest

from grafy_core.documents import PngFile, file_artifact
from grafy_core.file_contracts import BLOB_FILE
from grafy_core.plugins import NodeRegistration, PluginRegistrationError
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.port_check import check_port_declarations
from grafy_workbench.file.nodes import InterpretFileNode


def test_a_swapped_blob_declaration_fails_the_startup_check() -> None:
    values = ArtifactValues(
        (file_artifact(BLOB_FILE, PngFile),),
        uow=cast(UnitOfWorkPort, object()),
        storage=cast(FileStoragePort, object()),
        bucket="artifacts",
        storage_backend="local",
    )

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "operator file.interpret@1 input port 'file' does not match file.blob@1"
        ),
    ):
        check_port_declarations(
            (NodeRegistration(node_class=InterpretFileNode, factory=None),),
            values,
        )

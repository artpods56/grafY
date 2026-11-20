from typing import Annotated, cast, final, override

import pytest
from pydantic import Field, StrictInt

from grafy_core.artifacts import NoConfig, NodeInput, NodeOutput
from grafy_core.documents import BlobFile, PngFile, file_artifact
from grafy_core.file_contracts import BLOB_FILE
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import (
    NodeRegistration,
    Plugin,
    PluginRegistrationError,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.port_check import check_port_declarations


FIXTURES = Plugin(slug="test.port_check", title="Port check fixtures")
FIXTURES.register_artifact_type_dependency(BLOB_FILE)


class ReadBlobInput(NodeInput):
    file: Annotated[BlobFile, Field(title="File")]


class ReadBlobOutput(NodeOutput):
    size: Annotated[StrictInt, Field(title="Size")]


@FIXTURES.node(operator_id="test.port_check.blob", version=1, title="Read blob")
@final
class ReadBlobNode(Node[NoConfig, ReadBlobInput, ReadBlobOutput]):
    """Reads one unrecognized file so its port class takes part in the startup check."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: ReadBlobInput,
        /,
    ) -> ReadBlobOutput:
        del context
        return ReadBlobOutput(size=len(await inputs.file.read()))


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
            "operator test.port_check.blob@1 input port 'file' "
            "does not match file.blob@1"
        ),
    ):
        check_port_declarations(
            (NodeRegistration(node_class=ReadBlobNode, factory=None),),
            values,
        )

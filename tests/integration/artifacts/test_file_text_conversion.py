"""A file.txt@1 artifact becomes scalar.text@1 on an edge, with no adapter node."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.models import CompiledEdge, CompiledNode
from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    RunEdgeRequest,
    RunNodeRequest,
)
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.canonical_conversions import TEXT_FILE_TO_TEXT
from grafy_core.file_contracts import TXT_FILE
from grafy_core.nodes import resolve_node_contracts
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.invocation import NodeInvocation
from grafy_core.runtime.persistence import ArtifactOutputWriter, ArtifactWriterRegistry
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry
from grafy_storage import LocalFileObjectStore
from grafy_workbench.file.resolvers import FileBytesResolver
from grafy_workbench.text.nodes import (
    TEXT_VALUE,
    ReplaceTextNode,
    TextValueOutputWriter,
    TextValueResolver,
)

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000970")


async def _seed_text_file(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
    content: bytes,
) -> ArtifactRef:
    stored = await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path=f"files/{TXT_FILE.key.id}/{sha256(content).hexdigest()}.txt",
            stream=BytesIO(content),
            content_type="text/plain",
            metadata={},
            allow_overwrite=True,
        )
    )
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=TXT_FILE.key.id,
        schema_version=TXT_FILE.key.schema_version,
        content_type="text/plain",
        bucket=stored.bucket,
        object_key=stored.path,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        metadata={},
    )
    async with uow as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


def _edge_values(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
) -> EdgeValueResolver:
    return EdgeValueResolver(
        resolvers=ResolverRegistry(
            [
                cast(
                    Resolver[object],
                    FileBytesResolver(source=TXT_FILE.key, storage=storage, uow=uow),
                ),
                cast(Resolver[object], TextValueResolver(uow=uow)),
            ]
        ),
        writers=ArtifactWriterRegistry(
            [cast(ArtifactOutputWriter, TextValueOutputWriter(uow=uow))]
        ),
        unit_of_work=uow,
    )


async def _convert(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
    source: ArtifactRef,
) -> ArtifactRef:
    node = ReplaceTextNode()
    target = CompiledNode(
        request=RunNodeRequest(
            kind="builtin",
            id="target",
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            config={"search": "unused", "replacement": "unused"},
        ),
        node=node,
        registration=None,
        resolved_contracts=resolve_node_contracts(node, {}),
        invocation=NodeInvocation(),
        artifact_type_bindings={},
    )
    edge = CompiledEdge(
        request=RunEdgeRequest(
            from_node="source",
            from_port="file",
            to_node="target",
            to_port="text",
            conversion_path=[
                ArtifactConversionRequest(
                    id=TEXT_FILE_TO_TEXT.key.id,
                    version=TEXT_FILE_TO_TEXT.key.version,
                )
            ],
        ),
        projection=None,
        conversion_path=(TEXT_FILE_TO_TEXT,),
    )
    inputs = await _edge_values(storage, uow).assemble_inputs(
        target,
        (edge,),
        {"source": {"file": source}},
        uuid4(),
        WORKSPACE_ID,
    )
    converted = inputs["text"]
    assert isinstance(converted, ArtifactRef)
    return converted


@pytest.mark.asyncio
async def test_text_file_becomes_scalar_text_in_flight(tmp_path: Path) -> None:
    storage = LocalFileObjectStore(tmp_path)
    uow = InMemoryUnitOfWork()
    source = await _seed_text_file(storage, uow, "zażółć gęślą\njaźń\n".encode())

    converted = await _convert(storage, uow, source)

    assert converted.key() == TEXT_VALUE.key
    assert (
        await TextValueResolver(uow=uow).resolve(converted, WORKSPACE_ID)
        == "zażółć gęślą\njaźń\n"
    )
    async with uow as entered:
        artifact = await entered.artifacts.get(WORKSPACE_ID, converted.artifact_id)
    assert artifact is not None
    assert artifact.metadata["source_artifact_id"] == str(source.artifact_id)
    assert artifact.metadata["conversion_id"] == TEXT_FILE_TO_TEXT.key.id


@pytest.mark.asyncio
async def test_byte_order_mark_does_not_leak_into_the_text(tmp_path: Path) -> None:
    storage = LocalFileObjectStore(tmp_path)
    uow = InMemoryUnitOfWork()
    source = await _seed_text_file(storage, uow, b"\xef\xbb\xbfhello")

    converted = await _convert(storage, uow, source)

    assert await TextValueResolver(uow=uow).resolve(converted, WORKSPACE_ID) == "hello"


@pytest.mark.asyncio
async def test_bytes_that_are_not_utf8_fail_the_conversion_step(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path)
    uow = InMemoryUnitOfWork()
    source = await _seed_text_file(storage, uow, b"\xff\xfe\x00 not utf-8")

    with pytest.raises(GraphExecutionError, match="Failed conversion step 1/1"):
        _ = await _convert(storage, uow, source)

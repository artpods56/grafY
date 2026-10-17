from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from grafy_core.artifact_contracts import (
    TEXT_VALUE,
    TextValue,
    TextValuePayload,
)
from grafy_core.artifacts import ArtifactRef
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from pydantic import ValidationError

from grafy_workbench.text.nodes import (
    MARKDOWN,
    TEXT,
    MarkdownValue,
    TextInputConfig,
    TextInputInput,
    TextInputNode,
    TextValueOutputWriter,
    TextValueResolver,
)

TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def test_text_payload_keeps_legacy_public_identity() -> None:
    assert TextValuePayload is TextValue
    assert TextValuePayload.model_json_schema()["title"] == "TextValue"


@pytest.mark.asyncio
async def test_text_input_preserves_multiline_text() -> None:
    output = await TextInputNode().run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="input"),
        TextInputConfig(text="first line\n\nthird line\n"),
        TextInputInput(),
    )

    assert output.text == "first line\n\nthird line\n"
    text_schema = TextInputConfig.model_json_schema()["properties"]["text"]
    assert text_schema["format"] == "textarea"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (TextValuePayload, {"value": 1}),
        (TextInputConfig, {"text": 1}),
    ],
)
def test_text_models_reject_invalid_values(
    model: type[TextValuePayload | TextInputConfig],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_text_release_does_not_own_canonical_conversions() -> None:
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()

    assert TEXT.artifact_conversions == ()


def test_markdown_artifact_is_nominally_registered() -> None:
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()

    markdown_spec = next(
        artifact_type
        for artifact_type in registry.artifact_types
        if artifact_type.key == MARKDOWN.key
    )

    assert MARKDOWN.key.id == "text.markdown"
    assert MARKDOWN.key.schema_version == 1
    assert MARKDOWN.payload_schema == MarkdownValue.model_json_schema()
    assert [projection.path for projection in markdown_spec.field_projections] == [
        ("markdown",)
    ]
    assert [projection.target for projection in markdown_spec.field_projections] == [
        TEXT_VALUE.key
    ]


@pytest.mark.asyncio
async def test_markdown_inline_factories_round_trip_typed_payload(
    tmp_path: Path,
) -> None:
    uow = InMemoryUnitOfWork()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=cast(FileStoragePort, object()),
        uow=uow,
        bucket="artifacts",
    )
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()
    writers = {
        writer.artifact_type: writer for writer in registry.build_writers(context)
    }
    resolvers = {
        resolver.source: resolver for resolver in registry.build_resolvers(context)
    }
    source = "## Exact source\n\n| A | B |\n| - | - |\n| 1 | 2 |\n"
    payload = MarkdownValue(markdown=source)

    ref = await writers[MARKDOWN.key].write(
        payload,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="markdown",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )

    assert await resolvers[MARKDOWN.key].resolve(ref, TEST_WORKSPACE_ID) == payload
    async with uow as entered:
        artifact = await entered.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.inline_payload == {"markdown": source}


@pytest.mark.asyncio
async def test_text_value_adapters_preserve_inline_payload_and_metadata() -> None:
    uow = InMemoryUnitOfWork()
    source_ref = ArtifactRef(
        artifact_id=UUID("00000000-0000-0000-0000-000000000042"),
        artifact_type="scalar.integer",
        schema_version=1,
    )
    writer = TextValueOutputWriter(uow=uow)
    ref = await writer.write(
        "persisted text",
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="text",
            ),
            provenance=MaterializationProvenance(
                refs_by_input={"value": (source_ref,)}
            ),
            metadata={
                "conversion_id": "builtin.scalar.integer_to_text",
                "conversion_version": 1,
            },
        ),
    )
    resolver = TextValueResolver(uow=uow)

    assert await resolver.resolve(ref, TEST_WORKSPACE_ID) == "persisted text"
    async with uow as entered:
        artifact = await entered.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.inline_payload == {"value": "persisted text"}
    assert artifact.metadata == {
        "producer_node_id": "text",
        "provenance": {
            "value": [
                {
                    "artifact_id": str(source_ref.artifact_id),
                    "artifact_type": "scalar.integer",
                    "schema_version": 1,
                }
            ]
        },
        "conversion_id": "builtin.scalar.integer_to_text",
        "conversion_version": 1,
    }

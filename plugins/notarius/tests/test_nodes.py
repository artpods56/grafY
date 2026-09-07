import asyncio
import json
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, JsonObject
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.nodes import NodeExecutionContext, UserFacingNodeError

from grafy_plugin.artifacts import (
    StructuredExtractionDataset,
    StructuredExtractionItem,
)
from grafy_plugin.nodes import (
    ExtractionToTableConfig,
    ExtractionToTableInput,
    ExtractionToTableNode,
    StructuredDatasetExtractionConfig,
    StructuredDatasetExtractionInput,
    StructuredDatasetExtractionNode,
)
from grafy_plugin.processing import (
    ConversationMessage,
    ContextStrategySelection,
    MessageRole,
    ProviderResponse,
    ProviderSettings,
    StructuredCompletionError,
)


SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "continued": {"type": "boolean"},
                    },
                    "required": ["name", "continued"],
                    "additionalProperties": False,
                },
            },
            "context": {
                "type": "object",
                "properties": {"open_record": {"type": ["string", "null"]}},
                "required": ["open_record"],
                "additionalProperties": False,
            },
        },
        "required": ["records", "context"],
        "additionalProperties": False,
    }
)


def image_ref() -> ArtifactRef:
    return ArtifactRef.from_key(artifact_id=uuid4(), key=RASTER_IMAGE.key)


class FakeProvider:
    def __init__(self, responses: list[JsonObject]) -> None:
        self.responses = responses
        self.calls: list[Sequence[ConversationMessage]] = []

    async def complete(
        self,
        messages: Sequence[ConversationMessage],
        json_schema: str,
        settings: ProviderSettings,
        api_key: SecretStr,
        *,
        workspace_id: UUID,
    ) -> ProviderResponse:
        del json_schema, settings, api_key, workspace_id
        self.calls.append(messages)
        value = self.responses[len(self.calls) - 1]
        return ProviderResponse(
            content=json.dumps(value),
            structured_value=value,
            model="test-model",
        )


class QueueProvider:
    def __init__(self, outcomes: list[JsonObject | StructuredCompletionError]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[Sequence[ConversationMessage]] = []

    async def complete(
        self,
        messages: Sequence[ConversationMessage],
        json_schema: str,
        settings: ProviderSettings,
        api_key: SecretStr,
        *,
        workspace_id: UUID,
    ) -> ProviderResponse:
        del json_schema, settings, api_key, workspace_id
        self.calls.append(messages)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, StructuredCompletionError):
            raise outcome
        return ProviderResponse(
            content=json.dumps(outcome),
            structured_value=outcome,
            model="test-model",
        )


class IndependentProvider:
    def __init__(self) -> None:
        self.calls: list[Sequence[ConversationMessage]] = []

    async def complete(
        self,
        messages: Sequence[ConversationMessage],
        json_schema: str,
        settings: ProviderSettings,
        api_key: SecretStr,
        *,
        workspace_id: UUID,
    ) -> ProviderResponse:
        del json_schema, settings, api_key, workspace_id
        self.calls.append(messages)
        filename = messages[-1].text.split("<FILENAME>", 1)[1].split("</FILENAME>", 1)[0]
        if filename == "page-1.jpg":
            await asyncio.sleep(0.02)
        value = responses_value(filename, False)
        return ProviderResponse(
            content=json.dumps(value),
            structured_value=value,
            model="test-model",
        )


class FakeImageReader:
    def __init__(self, filenames: Mapping[UUID, str]) -> None:
        self.filenames = filenames

    async def filename(self, ref: ArtifactRef, *, workspace_id: UUID) -> str:
        del workspace_id
        return self.filenames[ref.artifact_id]

    async def data_url(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
        remaining_total_bytes: int,
    ) -> tuple[str, int]:
        del ref, workspace_id, remaining_total_bytes
        return "data:image/png;base64,eA==", 1


class FakeSecretResolver:
    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        return SecretStr("test-key")

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        return "test-revision"


@pytest.mark.asyncio
async def test_sliding_window_attaches_next_image_and_keeps_previous_exchange() -> None:
    refs = [image_ref(), image_ref(), image_ref()]
    filenames = {
        refs[0].artifact_id: "page-1.jpg",
        refs[1].artifact_id: "page-2.jpg",
        refs[2].artifact_id: "page-3.jpg",
    }
    responses: list[JsonObject] = [
        {"records": [{"name": "A", "continued": True}], "context": {"open_record": "A"}},
        {"records": [{"name": "A", "continued": False}], "context": {"open_record": None}},
        {"records": [{"name": "B", "continued": False}], "context": {"open_record": None}},
    ]
    provider = FakeProvider(responses)
    node = StructuredDatasetExtractionNode(
        provider=provider,
        image_reader=FakeImageReader(filenames),
        node_secrets=FakeSecretResolver(),
    )

    output = await node.run(
        NodeExecutionContext(workspace_id=uuid4(), node_id="extract"),
        StructuredDatasetExtractionConfig(window_size=1),
        StructuredDatasetExtractionInput(
            images=ArtifactRefSequence.from_key(
                key=RASTER_IMAGE.key,
                item_refs=refs,
            ),
            system_prompt="Extract faithfully.",
            instruction="Extract records from the current image.",
            json_schema=SCHEMA,
        ),
    )

    assert [item.source_filename for item in output.dataset.items] == [
        "page-1.jpg",
        "page-2.jpg",
        "page-3.jpg",
    ]
    first_current = provider.calls[0][-1]
    assert first_current.role is MessageRole.USER
    assert first_current.image_refs == (refs[0], refs[1])
    assert '<IMAGE INDEX="1" ROLE="next_page_lookahead"/>' in first_current.text

    second_call = provider.calls[1]
    assert [message.role for message in second_call] == [
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert second_call[1].image_refs == ()
    assert second_call[-1].image_refs == (refs[1], refs[2])
    assert provider.calls[-1][-1].image_refs == (refs[2],)
    assert "<NEXT_ITEM>null</NEXT_ITEM>" in provider.calls[-1][-1].text


@pytest.mark.asyncio
async def test_independent_processing_is_parallel_and_preserves_input_order() -> None:
    refs = [image_ref(), image_ref()]
    filenames = {
        refs[0].artifact_id: "page-1.jpg",
        refs[1].artifact_id: "page-2.jpg",
    }
    provider = IndependentProvider()
    node = StructuredDatasetExtractionNode(
        provider=provider,
        image_reader=FakeImageReader(filenames),
        node_secrets=FakeSecretResolver(),
    )

    output = await node.run(
        NodeExecutionContext(workspace_id=uuid4(), node_id="extract"),
        StructuredDatasetExtractionConfig(
            context_strategy=ContextStrategySelection.INDEPENDENT,
            max_concurrent=2,
        ),
        StructuredDatasetExtractionInput(
            images=ArtifactRefSequence.from_key(
                key=RASTER_IMAGE.key,
                item_refs=refs,
            ),
            system_prompt="Extract faithfully.",
            instruction="Extract records from the current image.",
            json_schema=SCHEMA,
        ),
    )

    assert len(provider.calls) == 2
    assert all(
        [message.role for message in call] == [MessageRole.SYSTEM, MessageRole.USER]
        for call in provider.calls
    )
    assert [item.source_filename for item in output.dataset.items] == [
        "page-1.jpg",
        "page-2.jpg",
    ]


@pytest.mark.asyncio
async def test_extraction_retries_invalid_json_then_keeps_the_valid_page() -> None:
    refs = [image_ref()]
    filenames = {refs[0].artifact_id: "page-1.jpg"}
    valid = responses_value("A", False)
    provider = QueueProvider(
        [
            StructuredCompletionError(
                "Provider returned invalid JSON for model 'test-model'"
            ),
            valid,
        ]
    )
    node = StructuredDatasetExtractionNode(
        provider=provider,
        image_reader=FakeImageReader(filenames),
        node_secrets=FakeSecretResolver(),
    )

    output = await node.run(
        NodeExecutionContext(workspace_id=uuid4(), node_id="extract"),
        StructuredDatasetExtractionConfig(max_retries=1),
        StructuredDatasetExtractionInput(
            images=ArtifactRefSequence.from_key(
                key=RASTER_IMAGE.key,
                item_refs=refs,
            ),
            system_prompt="Extract faithfully.",
            instruction="Extract records from the current image.",
            json_schema=SCHEMA,
        ),
    )

    assert len(provider.calls) == 2
    assert output.dataset.items[0].structured_value == valid


@pytest.mark.asyncio
async def test_extraction_records_a_failed_page_and_continues() -> None:
    refs = [image_ref(), image_ref()]
    filenames = {
        refs[0].artifact_id: "page-1.jpg",
        refs[1].artifact_id: "page-2.jpg",
    }
    invalid_json = StructuredCompletionError(
        "Provider returned invalid JSON for model 'test-model'"
    )
    second_page = responses_value("B", False)
    provider = QueueProvider([invalid_json, invalid_json, second_page])
    node = StructuredDatasetExtractionNode(
        provider=provider,
        image_reader=FakeImageReader(filenames),
        node_secrets=FakeSecretResolver(),
    )

    output = await node.run(
        NodeExecutionContext(workspace_id=uuid4(), node_id="extract"),
        StructuredDatasetExtractionConfig(max_retries=1, window_size=1),
        StructuredDatasetExtractionInput(
            images=ArtifactRefSequence.from_key(
                key=RASTER_IMAGE.key,
                item_refs=refs,
            ),
            system_prompt="Extract faithfully.",
            instruction="Extract records from the current image.",
            json_schema=SCHEMA,
        ),
    )

    assert len(provider.calls) == 3
    failed = output.dataset.items[0].structured_value
    assert failed["records"] == [
        {
            "extraction_error": (
                "Extraction failed for item 1, page-1.jpg: Provider returned "
                "invalid JSON for model 'test-model'"
            )
        }
    ]
    assert output.dataset.items[1].structured_value == second_page
    assert [message.role for message in provider.calls[-1]] == [
        MessageRole.SYSTEM,
        MessageRole.USER,
    ]


@pytest.mark.asyncio
async def test_extraction_to_table_infers_single_record_array() -> None:
    first_image_id = uuid4()
    second_image_id = uuid4()
    dataset = StructuredExtractionDataset(
        json_schema=SCHEMA,
        context_strategy="sliding_window",
        lookahead_images=True,
        items=[
            StructuredExtractionItem(
                source_index=0,
                source_image_id=first_image_id,
                source_filename="page-1.jpg",
                structured_value=responses_value("A", True),
                model="test-model",
            ),
            StructuredExtractionItem(
                source_index=1,
                source_image_id=second_image_id,
                source_filename="page-2.jpg",
                structured_value=responses_value("B", False),
                model="test-model",
            ),
        ],
    )

    output = await ExtractionToTableNode().run(
        NodeExecutionContext(workspace_id=uuid4(), node_id="to-table"),
        ExtractionToTableConfig(),
        ExtractionToTableInput(dataset=dataset),
    )

    assert [column.id for column in output.table.columns] == [
        "source_index",
        "source_filename",
        "source_image_id",
        "name",
        "continued",
    ]
    assert output.table.rows[0]["name"] == "A"
    assert output.table.rows[1]["source_filename"] == "page-2.jpg"


@pytest.mark.asyncio
async def test_extraction_to_table_rejects_ambiguous_arrays() -> None:
    ambiguous_schema = json.dumps(
        {
            "type": "object",
            "properties": {
                "records": {"type": "array", "items": {"type": "object"}},
                "notes": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": False,
        }
    )
    dataset = StructuredExtractionDataset(
        json_schema=ambiguous_schema,
        context_strategy="independent",
        lookahead_images=False,
        items=[],
    )

    with pytest.raises(UserFacingNodeError, match="multiple arrays"):
        await ExtractionToTableNode().run(
            NodeExecutionContext(workspace_id=uuid4(), node_id="to-table"),
            ExtractionToTableConfig(),
            ExtractionToTableInput(dataset=dataset),
        )


def responses_value(name: str, continued: bool) -> JsonObject:
    return {
        "records": [{"name": name, "continued": continued}],
        "context": {"open_record": name if continued else None},
    }

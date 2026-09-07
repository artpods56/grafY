import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import json
from typing import Protocol, cast
from uuid import UUID

from pydantic import SecretStr

from grafy_core.artifacts import ArtifactRef, JsonObject

from grafy_plugin.artifacts import StructuredExtractionItem


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: MessageRole
    text: str
    image_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Conversation:
    messages: tuple[ConversationMessage, ...] = ()

    def add(self, message: ConversationMessage) -> "Conversation":
        return Conversation(messages=(*self.messages, message))


@dataclass(slots=True)
class PredictionDataItem:
    index: int
    image_ref: ArtifactRef
    filename: str
    prediction: JsonObject | None = None
    provider_response: "ProviderResponse | None" = None


@dataclass(frozen=True, slots=True)
class SequenceState:
    conversation: Conversation
    items_processed: int = 0
    current_item_index: int = 0


class ContextStrategySelection(StrEnum):
    INDEPENDENT = "independent"
    SLIDING_WINDOW = "sliding_window"
    FULL_HISTORY = "full_history"


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    base_url: str
    model: str
    temperature: float
    max_completion_tokens: int
    timeout_ms: int
    max_retries: int
    schema_name: str
    strict: bool


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    content: str
    structured_value: JsonObject
    model: str
    response_id: str | None = None
    finish_reason: str | None = None
    usage: JsonObject | None = None


class StructuredCompletionProvider(Protocol):
    async def complete(
        self,
        messages: Sequence[ConversationMessage],
        json_schema: str,
        settings: ProviderSettings,
        api_key: SecretStr,
        *,
        workspace_id: UUID,
    ) -> ProviderResponse: ...


class StructuredCompletionError(RuntimeError):
    """Provider error whose message is safe to show to a graph user."""


class ItemProcessingError(RuntimeError):
    """Structured extraction failure with source-item context."""


def _object_array_fields(schema: dict[str, object]) -> list[str]:
    raw_properties = schema.get("properties")
    if not isinstance(raw_properties, dict):
        return []
    properties = cast(dict[object, object], raw_properties)
    fields: list[str] = []
    for name, raw_definition in properties.items():
        if not isinstance(name, str) or not isinstance(raw_definition, dict):
            continue
        definition = cast(dict[object, object], raw_definition)
        items = definition.get("items")
        if definition.get("type") == "array" and isinstance(items, dict):
            item_definition = cast(dict[object, object], items)
            if item_definition.get("type") == "object":
                fields.append(name)
    return fields


def failed_extraction_value(json_schema: str, message: str) -> JsonObject:
    error_row: JsonObject = {"extraction_error": message}
    value: JsonObject = {"extraction_error": message}
    try:
        parsed = json.loads(json_schema)
    except json.JSONDecodeError:
        return value
    if not isinstance(parsed, dict):
        return value
    for field in _object_array_fields(cast(dict[str, object], parsed)):
        value[field] = [error_row]
    return value


class MessageBuilder:
    def __init__(self, *, system_prompt: str, instruction: str) -> None:
        self._system_prompt = system_prompt
        self._instruction = instruction

    def system_message(self) -> ConversationMessage:
        return ConversationMessage(
            role=MessageRole.SYSTEM,
            text=self._system_prompt,
        )

    def user_message(
        self,
        *,
        item: PredictionDataItem,
        next_item: PredictionDataItem | None,
        item_count: int,
        include_lookahead: bool,
    ) -> ConversationMessage:
        next_item_xml = "<NEXT_ITEM>null</NEXT_ITEM>"
        image_refs = (item.image_ref,)
        attached_images = '<IMAGE INDEX="0" ROLE="current"/>'
        if include_lookahead and next_item is not None:
            next_item_xml = (
                "<NEXT_ITEM>\n"
                f"<INDEX>{next_item.index}</INDEX>\n"
                f"<FILENAME>{next_item.filename}</FILENAME>\n"
                "<USAGE>Use the next image only to decide whether content at the "
                "end of the current image continues. Do not extract content that "
                "belongs only to the next image.</USAGE>\n"
                "</NEXT_ITEM>"
            )
            image_refs = (item.image_ref, next_item.image_ref)
            attached_images += '\n<IMAGE INDEX="1" ROLE="next_page_lookahead"/>'

        text = (
            "<EXTRACTION_INSTRUCTION>\n"
            f"{self._instruction}\n"
            "</EXTRACTION_INSTRUCTION>\n\n"
            "<MANAGED_CONTEXT>\n"
            "<CURRENT_ITEM>\n"
            f"<INDEX>{item.index}</INDEX>\n"
            f"<TOTAL>{item_count}</TOTAL>\n"
            f"<FILENAME>{item.filename}</FILENAME>\n"
            "</CURRENT_ITEM>\n"
            f"{next_item_xml}\n"
            "<ATTACHED_IMAGES>\n"
            f"{attached_images}\n"
            "</ATTACHED_IMAGES>\n"
            "</MANAGED_CONTEXT>\n\n"
            "<OUTPUT_REQUIREMENTS>Return only one JSON object conforming to the "
            "supplied JSON Schema. Extract the current image only.</OUTPUT_REQUIREMENTS>"
        )
        return ConversationMessage(
            role=MessageRole.USER,
            text=text,
            image_refs=image_refs,
        )


class ContextStrategy(Protocol):
    selection: ContextStrategySelection

    def initial_state(self, message_builder: MessageBuilder) -> SequenceState: ...

    def prepare_state(
        self,
        *,
        state: SequenceState,
        message: ConversationMessage,
        message_builder: MessageBuilder,
    ) -> SequenceState: ...

    def update_state(self, state: SequenceState) -> SequenceState: ...


@dataclass(frozen=True, slots=True)
class IndependentStrategy:
    selection = ContextStrategySelection.INDEPENDENT

    def initial_state(self, message_builder: MessageBuilder) -> SequenceState:
        return SequenceState(
            conversation=Conversation().add(message_builder.system_message())
        )

    def prepare_state(
        self,
        *,
        state: SequenceState,
        message: ConversationMessage,
        message_builder: MessageBuilder,
    ) -> SequenceState:
        del state
        conversation = Conversation().add(message_builder.system_message()).add(message)
        return SequenceState(conversation=conversation)

    def update_state(self, state: SequenceState) -> SequenceState:
        return SequenceState(
            conversation=Conversation(),
            items_processed=state.items_processed + 1,
            current_item_index=state.current_item_index,
        )


@dataclass(frozen=True, slots=True)
class FullHistoryStrategy:
    selection = ContextStrategySelection.FULL_HISTORY

    def initial_state(self, message_builder: MessageBuilder) -> SequenceState:
        return SequenceState(
            conversation=Conversation().add(message_builder.system_message())
        )

    def prepare_state(
        self,
        *,
        state: SequenceState,
        message: ConversationMessage,
        message_builder: MessageBuilder,
    ) -> SequenceState:
        conversation = state.conversation
        if not conversation.messages:
            conversation = conversation.add(message_builder.system_message())
        return replace(state, conversation=conversation.add(message))

    def update_state(self, state: SequenceState) -> SequenceState:
        messages = tuple(
            replace(message, image_refs=())
            if message.role is MessageRole.USER
            else message
            for message in state.conversation.messages
        )
        return replace(
            state,
            conversation=Conversation(messages=messages),
            items_processed=state.items_processed + 1,
        )


@dataclass(frozen=True, slots=True)
class SlidingWindowStrategy:
    window_size: int
    selection = ContextStrategySelection.SLIDING_WINDOW

    def initial_state(self, message_builder: MessageBuilder) -> SequenceState:
        return SequenceState(
            conversation=Conversation().add(message_builder.system_message())
        )

    def prepare_state(
        self,
        *,
        state: SequenceState,
        message: ConversationMessage,
        message_builder: MessageBuilder,
    ) -> SequenceState:
        conversation = state.conversation
        if not conversation.messages:
            conversation = conversation.add(message_builder.system_message())
        return replace(state, conversation=conversation.add(message))

    def update_state(self, state: SequenceState) -> SequenceState:
        system_messages = tuple(
            message
            for message in state.conversation.messages
            if message.role is MessageRole.SYSTEM
        )
        exchange_messages = tuple(
            replace(message, image_refs=())
            if message.role is MessageRole.USER
            else message
            for message in state.conversation.messages
            if message.role is not MessageRole.SYSTEM
        )
        exchange_messages = exchange_messages[-self.window_size * 2 :]
        return replace(
            state,
            conversation=Conversation(
                messages=(*system_messages, *exchange_messages),
            ),
            items_processed=state.items_processed + 1,
        )


class ItemProcessor:
    def __init__(
        self,
        *,
        provider: StructuredCompletionProvider,
        json_schema: str,
        settings: ProviderSettings,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> None:
        self._provider = provider
        self._json_schema = json_schema
        self._settings = settings
        self._api_key = api_key
        self._workspace_id = workspace_id

    async def process_async(
        self,
        *,
        item: PredictionDataItem,
        state: SequenceState,
    ) -> SequenceState:
        attempts = 1 + self._settings.max_retries
        response: ProviderResponse | None = None
        last_error: StructuredCompletionError | None = None
        for _ in range(attempts):
            try:
                response = await self._provider.complete(
                    state.conversation.messages,
                    self._json_schema,
                    self._settings,
                    self._api_key,
                    workspace_id=self._workspace_id,
                )
                break
            except StructuredCompletionError as exc:
                last_error = exc
        if response is None:
            message = (
                f"Extraction failed for item {item.index + 1}, {item.filename}: "
                f"{last_error}"
            )
            structured_value = failed_extraction_value(self._json_schema, message)
            item.prediction = structured_value
            item.provider_response = ProviderResponse(
                content=json.dumps(structured_value, ensure_ascii=False),
                structured_value=structured_value,
                model=self._settings.model,
                finish_reason="error",
            )
            messages = state.conversation.messages
            if messages and messages[-1].role is MessageRole.USER:
                conversation = Conversation(messages=messages[:-1])
            else:
                conversation = state.conversation
            return replace(state, conversation=conversation)
        item.prediction = response.structured_value
        item.provider_response = response
        assistant_message = ConversationMessage(
            role=MessageRole.ASSISTANT,
            text=response.content,
        )
        return replace(
            state,
            conversation=state.conversation.add(assistant_message),
        )


class ProgressCallback(Protocol):
    async def __call__(
        self,
        message: str,
        *,
        current: int,
        total: int,
    ) -> None: ...


class DatasetProcessor:
    def __init__(
        self,
        *,
        item_processor: ItemProcessor,
        message_builder: MessageBuilder,
        context_strategy: ContextStrategy,
        include_lookahead: bool,
        progress: ProgressCallback,
    ) -> None:
        self._item_processor = item_processor
        self._message_builder = message_builder
        self._context_strategy = context_strategy
        self._include_lookahead = include_lookahead
        self._progress = progress

    async def process_sequence_async(
        self,
        items: Sequence[PredictionDataItem],
    ) -> Sequence[PredictionDataItem]:
        state = self._context_strategy.initial_state(self._message_builder)
        item_count = len(items)
        for index, item in enumerate(items):
            await self._progress(
                f"Extracting {item.filename}",
                current=index + 1,
                total=item_count,
            )
            current_state = replace(state, current_item_index=index)
            next_item = items[index + 1] if index + 1 < item_count else None
            message = self._message_builder.user_message(
                item=item,
                next_item=next_item,
                item_count=item_count,
                include_lookahead=self._include_lookahead,
            )
            prepared_state = self._context_strategy.prepare_state(
                state=current_state,
                message=message,
                message_builder=self._message_builder,
            )
            processed_state = await self._item_processor.process_async(
                item=item,
                state=prepared_state,
            )
            state = self._context_strategy.update_state(processed_state)
        await self._progress(
            "Extraction complete",
            current=item_count,
            total=item_count,
        )
        return items

    async def process_parallel_async(
        self,
        items: Sequence[PredictionDataItem],
        *,
        max_concurrent: int,
    ) -> Sequence[PredictionDataItem]:
        semaphore = asyncio.Semaphore(max_concurrent)
        item_count = len(items)

        await asyncio.gather(
            *(
                self._process_independent_item(
                    semaphore=semaphore,
                    items=items,
                    index=index,
                    item=item,
                )
                for index, item in enumerate(items)
            )
        )
        await self._progress(
            "Extraction complete",
            current=item_count,
            total=item_count,
        )
        return items

    async def _process_independent_item(
        self,
        *,
        semaphore: asyncio.Semaphore,
        items: Sequence[PredictionDataItem],
        index: int,
        item: PredictionDataItem,
    ) -> None:
        async with semaphore:
            item_count = len(items)
            await self._progress(
                f"Extracting {item.filename}",
                current=index + 1,
                total=item_count,
            )
            next_item = items[index + 1] if index + 1 < item_count else None
            message = self._message_builder.user_message(
                item=item,
                next_item=next_item,
                item_count=item_count,
                include_lookahead=self._include_lookahead,
            )
            state = self._context_strategy.initial_state(self._message_builder)
            prepared_state = self._context_strategy.prepare_state(
                state=replace(state, current_item_index=index),
                message=message,
                message_builder=self._message_builder,
            )
            await self._item_processor.process_async(
                item=item,
                state=prepared_state,
            )


def extraction_items(
    items: Sequence[PredictionDataItem],
) -> list[StructuredExtractionItem]:
    extracted: list[StructuredExtractionItem] = []
    for item in items:
        if item.prediction is None or item.provider_response is None:
            raise RuntimeError(
                f"Extraction item {item.index} ({item.filename}) has no response"
            )
        response = item.provider_response
        extracted.append(
            StructuredExtractionItem(
                source_index=item.index,
                source_image_id=item.image_ref.artifact_id,
                source_filename=item.filename,
                structured_value=item.prediction,
                model=response.model,
                response_id=response.response_id,
                finish_reason=response.finish_reason,
                usage=response.usage or {},
            )
        )
    return extracted


__all__ = [
    "ContextStrategySelection",
    "ConversationMessage",
    "DatasetProcessor",
    "FullHistoryStrategy",
    "IndependentStrategy",
    "ItemProcessingError",
    "ItemProcessor",
    "MessageBuilder",
    "MessageRole",
    "PredictionDataItem",
    "ProviderResponse",
    "ProviderSettings",
    "SlidingWindowStrategy",
    "StructuredCompletionProvider",
    "StructuredCompletionError",
    "extraction_items",
]

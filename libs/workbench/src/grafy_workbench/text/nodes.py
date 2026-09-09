import json
from hashlib import sha256
from typing import Annotated, cast, final, override
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from grafy_core.artifact_contracts import TEXT_VALUE, TextValuePayload
from grafy_core.artifacts import (
    Artifact,
    ArtifactExportFormat,
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.errors import NotFoundError
from grafy_core.nodes import InPort, OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
    InlineModelOutputWriter,
)
from grafy_core.runtime.resolvers import (
    ArtifactContractError,
    InlineModelResolver,
    ResolutionError,
    Resolver,
)

from grafy_workbench.text.declaration import TEXT


class MarkdownValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: StrictStr


MARKDOWN = ArtifactTypeSpec(
    key=ArtifactTypeKey("text.markdown", 1),
    title="Markdown",
    payload_schema=cast(JsonObject, MarkdownValue.model_json_schema()),
    export_formats=(
        ArtifactExportFormat(
            format="txt",
            content_type="text/plain; charset=utf-8",
            filename="markdown.txt",
        ),
    ),
)


class TextInputConfig(NodeConfig):
    text: StrictStr = Field(
        description="Multiline text emitted by the node.",
        json_schema_extra={"format": "textarea"},
    )


class TextInputInput(NodeInput):
    pass


class TextInputOutput(NodeOutput):
    text: Annotated[
        StrictStr,
        OutPort(TEXT_VALUE),
        Field(description="The configured text value."),
    ]


@TEXT.function_node(
    operator_id="text.input",
    version=1,
    title="Text input",
    cache_policy=NodeCachePolicy.EXACT,
)
async def text_input(
    config: TextInputConfig, _inputs: TextInputInput
) -> TextInputOutput:
    """Produces one configured multiline text value."""
    return TextInputOutput(text=config.text)


TextInputNode = TEXT.nodes[-1].node_class


class AsMarkdownInput(NodeInput):
    text: Annotated[
        StrictStr,
        InPort(TEXT_VALUE),
        Field(description="Markdown source text to preserve."),
    ]


class AsMarkdownOutput(NodeOutput):
    markdown: Annotated[
        MarkdownValue,
        OutPort(MARKDOWN),
        Field(description="The same source text marked as Markdown."),
    ]


@TEXT.function_node(
    operator_id="text.as_markdown",
    version=1,
    title="As Markdown",
    cache_policy=NodeCachePolicy.EXACT,
)
async def as_markdown(
    _config: NoConfig,
    inputs: AsMarkdownInput,
) -> AsMarkdownOutput:
    """Marks text as Markdown without transforming its source."""
    return AsMarkdownOutput(markdown=MarkdownValue(markdown=inputs.text))


AsMarkdownNode = TEXT.nodes[-1].node_class


class SplitTextConfig(NodeConfig):
    separator: StrictStr = Field(
        min_length=1,
        description="Exact text used to separate the input into parts.",
    )


class SplitTextInput(NodeInput):
    text: Annotated[
        StrictStr,
        InPort(TEXT_VALUE),
        Field(description="Text value to split."),
    ]


class SplitTextOutput(NodeOutput):
    parts: Annotated[
        list[StrictStr],
        OutPort(TEXT_VALUE),
        Field(description="Ordered text parts, including empty parts."),
    ]


@TEXT.function_node(
    operator_id="text.split",
    version=1,
    title="Split text",
    cache_policy=NodeCachePolicy.EXACT,
)
async def split_text(
    config: SplitTextConfig, inputs: SplitTextInput
) -> SplitTextOutput:
    """Splits text on an exact separator while preserving empty parts."""
    return SplitTextOutput(parts=inputs.text.split(config.separator))


SplitTextNode = TEXT.nodes[-1].node_class


class ReplaceTextConfig(NodeConfig):
    search: StrictStr = Field(
        min_length=1,
        description="Exact text to find.",
    )
    replacement: StrictStr = Field(
        default="",
        description="Text substituted for every match.",
    )


class ReplaceTextInput(NodeInput):
    text: Annotated[
        StrictStr,
        InPort(TEXT_VALUE),
        Field(description="Text value in which replacements are made."),
    ]


class ReplaceTextOutput(NodeOutput):
    text: Annotated[
        StrictStr,
        OutPort(TEXT_VALUE),
        Field(description="Text after all exact replacements."),
    ]


@TEXT.function_node(
    operator_id="text.replace",
    version=1,
    title="Replace text",
    cache_policy=NodeCachePolicy.EXACT,
)
async def replace_text(
    config: ReplaceTextConfig,
    inputs: ReplaceTextInput,
) -> ReplaceTextOutput:
    """Replaces every exact occurrence of configured search text."""
    return ReplaceTextOutput(
        text=inputs.text.replace(config.search, config.replacement)
    )


ReplaceTextNode = TEXT.nodes[-1].node_class


class JoinTextConfig(NodeConfig):
    separator: StrictStr = Field(
        default="",
        description="Text inserted between adjacent parts.",
    )


class JoinTextInput(NodeInput):
    parts: Annotated[
        list[StrictStr],
        InPort(TEXT_VALUE),
        Field(description="Ordered text values to join."),
    ]


class JoinTextOutput(NodeOutput):
    text: Annotated[
        StrictStr,
        OutPort(TEXT_VALUE),
        Field(description="The joined text value."),
    ]


@TEXT.function_node(
    operator_id="text.join",
    version=1,
    title="Join text",
    cache_policy=NodeCachePolicy.EXACT,
)
async def join_text(config: JoinTextConfig, inputs: JoinTextInput) -> JoinTextOutput:
    """Joins an ordered text sequence with a configured separator."""
    return JoinTextOutput(text=config.separator.join(inputs.parts))


JoinTextNode = TEXT.nodes[-1].node_class


@final
class TextValueOutputWriter(ArtifactOutputWriter):
    artifact_type = TEXT_VALUE.key

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        try:
            payload = TextValuePayload.model_validate({"value": value})
        except ValidationError as exc:
            message = (
                f"Failed to serialize {self.artifact_type.id}@"
                f"{self.artifact_type.schema_version} value produced by node "
                f"{context.node_context.node_id!r}"
            )
            raise RuntimeError(message) from exc

        payload_json = cast(JsonObject, payload.model_dump(mode="json"))
        payload_bytes = json.dumps(
            payload_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        provenance: dict[str, object] = {
            input_name: [
                {
                    "artifact_id": str(ref.artifact_id),
                    "artifact_type": ref.artifact_type,
                    "schema_version": ref.schema_version,
                }
                for ref in refs
            ]
            for input_name, refs in context.provenance.refs_by_input.items()
        }
        metadata: JsonObject = {
            "producer_node_id": context.node_context.node_id,
        }
        if provenance:
            metadata["provenance"] = provenance
        metadata.update(context.metadata)
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=payload_json,
            byte_size=len(payload_bytes),
            sha256=sha256(payload_bytes).hexdigest(),
            metadata=metadata,
        )
        try:
            async with self._uow as uow:
                await uow.artifacts.add(artifact)
                await uow.commit()
        except Exception as exc:
            message = (
                f"Failed to persist {self.artifact_type.id}@"
                f"{self.artifact_type.schema_version} produced by node "
                f"{context.node_context.node_id!r}"
            )
            raise RuntimeError(message) from exc
        return artifact.ref()


@final
class TextValueResolver(Resolver[str]):
    source = TEXT_VALUE.key
    target: type[object] = str

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> str:
        if ref.key() != self.source:
            message = (
                f"Text resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for artifact {ref.artifact_id}"
            )
            raise ArtifactContractError(message)

        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            message = (
                "Artifact repository returned a different artifact ref for "
                f"text artifact {ref.artifact_id}"
            )
            raise ArtifactContractError(message)
        if artifact.inline_payload is None:
            message = (
                f"Text artifact {ref.artifact_id} does not have an inline JSON payload"
            )
            raise ArtifactContractError(message)

        try:
            return TextValuePayload.model_validate(artifact.inline_payload).value
        except ValidationError as exc:
            message = (
                f"Failed to resolve artifact {ref.artifact_id} as "
                f"{self.source.id}@{self.source.schema_version} text value"
            )
            raise ResolutionError(message) from exc


TEXT.register(
    Artifact(
        spec=TEXT_VALUE,
        resolver=lambda context: TextValueResolver(uow=context.uow),
        writer=lambda context: TextValueOutputWriter(uow=context.uow),
    )
)
TEXT.register(
    Artifact(
        spec=MARKDOWN,
        resolver=lambda context: InlineModelResolver(
            source=MARKDOWN.key,
            target=MarkdownValue,
            uow=context.uow,
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=MARKDOWN.key,
            model=MarkdownValue,
            uow=context.uow,
        ),
    )
)

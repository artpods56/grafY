from typing import Annotated, cast, final

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from grafy_core.artifact_contracts import TEXT_VALUE, TextValuePayload
from grafy_core.artifacts import (
    Artifact,
    ArtifactExportFormat,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.nodes import InPort, OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_workbench.text.declaration import TEXT
from grafy_workbench.scalar_persistence import ScalarOutputWriter, ScalarResolver


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
class TextValueOutputWriter(ScalarOutputWriter):
    """Keep the existing constructor used by runtime clients."""

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        super().__init__(artifact_type=TEXT_VALUE.key, model=TextValuePayload, uow=uow)


@final
class TextValueResolver(ScalarResolver[str]):
    """Keep the existing constructor used by runtime clients."""

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        super().__init__(
            source=TEXT_VALUE.key, target=str, model=TextValuePayload, uow=uow
        )


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

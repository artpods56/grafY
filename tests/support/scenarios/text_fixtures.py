"""Text-shaped engine fixtures: a transform, a splitter, a joiner, a marker.

These exist only so engine tests (conversion paths, map invocation, module
progress, plug structures) keep richer fixtures than the shipped catalog
offers. They carry ``test.text`` identities so they cannot enter the
production catalog, in the same way as the ``test.sequence`` fixtures.
"""

from typing import Annotated

from pydantic import Field, StrictStr

from grafy_core.artifact_contracts import MARKDOWN, TEXT_VALUE, MarkdownValue
from grafy_core.artifacts import NoConfig, NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import InPort, OutPort
from grafy_core.plugins import NodeCachePolicy, Plugin


TEXT_FIXTURES = Plugin(slug="test.text", title="Text fixtures")
TEXT_FIXTURES.register_artifact_type_dependency(TEXT_VALUE)
TEXT_FIXTURES.register_artifact_type_dependency(MARKDOWN)


class ReplaceTextInput(NodeInput):
    text: Annotated[StrictStr, InPort(TEXT_VALUE)]


class ReplaceTextOutput(NodeOutput):
    text: Annotated[StrictStr, OutPort(TEXT_VALUE)]


class ReplaceTextConfig(NodeConfig):
    search: StrictStr = Field(min_length=1, description="Exact text to find.")
    replacement: StrictStr = Field(default="", description="Replacement text.")


@TEXT_FIXTURES.function_node(
    operator_id="test.text.replace",
    version=1,
    title="Replace text",
    cache_policy=NodeCachePolicy.EXACT,
)
async def replace_text(
    config: ReplaceTextConfig, inputs: ReplaceTextInput
) -> ReplaceTextOutput:
    """Replaces every exact occurrence of the configured search text."""
    return ReplaceTextOutput(
        text=inputs.text.replace(config.search, config.replacement)
    )


ReplaceTextNode = TEXT_FIXTURES.nodes[-1].node_class


class SplitTextInput(NodeInput):
    text: Annotated[StrictStr, InPort(TEXT_VALUE)]


class SplitTextOutput(NodeOutput):
    parts: Annotated[
        list[StrictStr],
        OutPort(TEXT_VALUE),
        Field(description="Ordered text parts, including empty parts."),
    ]


class SplitTextConfig(NodeConfig):
    separator: StrictStr = Field(
        min_length=1,
        description="Exact text used to separate the input into parts.",
    )


@TEXT_FIXTURES.function_node(
    operator_id="test.text.split",
    version=1,
    title="Split text",
    cache_policy=NodeCachePolicy.EXACT,
)
async def split_text(
    config: SplitTextConfig, inputs: SplitTextInput
) -> SplitTextOutput:
    """Splits text on an exact separator while preserving empty parts."""
    return SplitTextOutput(parts=inputs.text.split(config.separator))


class JoinTextInput(NodeInput):
    parts: Annotated[
        list[StrictStr],
        InPort(TEXT_VALUE),
        Field(description="Ordered text values to join."),
    ]


class JoinTextOutput(NodeOutput):
    text: Annotated[StrictStr, OutPort(TEXT_VALUE)]


class JoinTextConfig(NodeConfig):
    separator: StrictStr = Field(
        default="",
        description="Text inserted between adjacent parts.",
    )


@TEXT_FIXTURES.function_node(
    operator_id="test.text.join",
    version=1,
    title="Join text",
    cache_policy=NodeCachePolicy.EXACT,
)
async def join_text(config: JoinTextConfig, inputs: JoinTextInput) -> JoinTextOutput:
    """Joins an ordered text sequence with a configured separator."""
    return JoinTextOutput(text=config.separator.join(inputs.parts))


class AsMarkdownInput(NodeInput):
    text: Annotated[StrictStr, InPort(TEXT_VALUE)]


class AsMarkdownOutput(NodeOutput):
    markdown: Annotated[MarkdownValue, OutPort(MARKDOWN)]


@TEXT_FIXTURES.function_node(
    operator_id="test.text.as_markdown",
    version=1,
    title="As Markdown",
    cache_policy=NodeCachePolicy.EXACT,
)
async def as_markdown(
    _config: NoConfig, inputs: AsMarkdownInput
) -> AsMarkdownOutput:
    """Marks text as Markdown without transforming its source."""
    return AsMarkdownOutput(markdown=MarkdownValue(markdown=inputs.text))


__all__ = [
    "TEXT_FIXTURES",
    "ReplaceTextNode",
]

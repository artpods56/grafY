from typing import Annotated

from pydantic import Field, StrictStr

from grafy_core.artifact_contracts import (
    HTML_PAGE,
    MARKDOWN,
    TEXT_VALUE,
    HtmlPage,
    MarkdownValue,
    TextValuePayload,
)
from grafy_core.artifacts import (
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.artifact_values import inline_model_artifact, scalar_artifact

from grafy_workbench.text.declaration import TEXT


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


TEXT.register(scalar_artifact(TEXT_VALUE, str, TextValuePayload))
TEXT.register(inline_model_artifact(MARKDOWN, MarkdownValue))
TEXT.register(inline_model_artifact(HTML_PAGE, HtmlPage))

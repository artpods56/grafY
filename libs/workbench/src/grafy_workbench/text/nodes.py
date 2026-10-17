from typing import Annotated, final

from pydantic import Field, StrictStr

from grafy_core.artifact_contracts import (
    MARKDOWN,
    TEXT_VALUE,
    MarkdownValue,
    TextValuePayload,
)
from grafy_core.artifacts import (
    Artifact,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.nodes import OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_workbench.text.declaration import TEXT
from grafy_workbench.scalar_persistence import ScalarOutputWriter, ScalarResolver


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

from typing import Annotated

from pydantic import Field, StrictStr

from grafy_core.artifacts import (
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.documents import RasterImage
from grafy_core.nodes import RefSequence
from grafy_core.plugins import NodeCachePolicy
from grafy_core.prompt_contracts import (
    PROMPT_MESSAGE,
    PromptMessage,
    PromptMessageRole,
)
from grafy_core.runtime.artifact_values import inline_model_artifact

import grafy_workbench.text.nodes as _text_nodes
from grafy_plugin_llm.declaration import LLM

_ = _text_nodes.__name__  # notes str before these ports


LLM.register(inline_model_artifact(PROMPT_MESSAGE, PromptMessage))


class PromptMessageConfig(NodeConfig):
    role: PromptMessageRole = Field(
        default=PromptMessageRole.USER,
        description="Role assigned to the prompt message.",
    )


class PromptMessageInput(NodeInput):
    text: Annotated[
        StrictStr,
        Field(title="Words", description="Text content of the prompt message."),
    ]
    images: Annotated[
        RefSequence[RasterImage] | None,
        Field(
            title="Pictures",
            description="Optional ordered image artifacts for a user message.",
        ),
    ] = None


class PromptMessageOutput(NodeOutput):
    message: Annotated[
        PromptMessage,
        Field(title="Instruction", description="The composed prompt message."),
    ]


@LLM.function_node(
    operator_id="prompt.message.create",
    version=2,
    title="Write an instruction",
    cache_policy=NodeCachePolicy.EXACT,
)
async def create_prompt_message(
    config: PromptMessageConfig,
    inputs: PromptMessageInput,
) -> PromptMessageOutput:
    """The words, and any pictures, you want the model to read."""
    if inputs.images is not None and not inputs.images.ordered:
        raise ValueError(
            "Cannot create a prompt message from unordered image sequence "
            f"{inputs.images.sequence_id}"
        )
    image_refs = [] if inputs.images is None else inputs.images.item_refs
    return PromptMessageOutput(
        message=PromptMessage(
            role=config.role,
            text=inputs.text,
            image_refs=image_refs,
        )
    )


CreatePromptMessageNode = LLM.nodes[-1].node_class


__all__ = [
    "CreatePromptMessageNode",
    "PromptMessageConfig",
    "PromptMessageInput",
    "PromptMessageOutput",
]

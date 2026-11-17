from grafy_core.runtime.artifact_values import inline_model_artifact

from grafy_plugin_llm import (  # noqa: F401
    openai_compatible,  # registers the llm.* and prompt.* operators on LLM
    prompt,
)
from grafy_plugin_llm.artifacts import COMPLETION, CompletionPayload
from grafy_plugin_llm.declaration import LLM


LLM.register(inline_model_artifact(COMPLETION, CompletionPayload))


__all__ = ["LLM"]

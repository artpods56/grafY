from grafy_plugin_llm import (  # noqa: F401
    openai_compatible,  # registers the llm.* and prompt.* operators on LLM
    prompt,
)
from grafy_plugin_llm.declaration import LLM


__all__ = ["LLM"]

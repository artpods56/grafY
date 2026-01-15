"""LLM cache adapter using pickle for automatic serialization."""

from pathlib import Path
from typing import final

from pydantic import BaseModel
from structlog import get_logger

from notarius.infrastructure.cache.adapters.pickle_cache import PickleCache
from notarius.infrastructure.llm.engine_adapter import CompletionResult
from notarius.infrastructure.llm.utils import parse_model_name
from notarius.shared.logger import Logger

logger = get_logger(__name__)


@final
class LLMCache(PickleCache[CompletionResult[BaseModel]]):
    """Type-safe cache for LLM responses using pickle serialization.

    Pickle automatically handles the complex nested structure of:
    - CompletionResult (dataclass)
    - BaseProviderResponse (dataclass)
    - Conversation (dataclass)
    - Pydantic models (BaseModel)

    No manual serialization/deserialization needed!

    Note: The generic type T is erased at runtime (pickle doesn't preserve it),
    but it helps with static type checking.
    """

    _item_type = CompletionResult
    _cache_type = "LLMCache"
    _default_size_limit: int = 10 * 1024 * 1024 * 1024  # 10GB for multimodal LLM

    def __init__(self, model_name: str, caches_dir: Path | None = None):
        super().__init__(
            cache_name=parse_model_name(model_name),
            caches_dir=caches_dir,
            size_limit=10 * 1024 * 1024 * 1024,
        )

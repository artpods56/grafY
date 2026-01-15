"""LayoutLMv3 cache adapter using pickle for automatic serialization."""

from pathlib import Path
from typing import TypedDict, override

from structlog import get_logger

from notarius.infrastructure.cache.adapters.pickle_cache import PickleCache
from notarius.infrastructure.ml_models.lmv3.engine_adapter import LMv3Response
from notarius.shared.logger import Logger

logger: Logger = get_logger(__name__)


class LMv3CacheKeyParams(TypedDict, total=False):
    """Type definition for LMv3 cache key parameters."""

    image_hash: str


class LMv3Cache(PickleCache[LMv3Response]):
    """Type-safe cache for LayoutLMv3 model predictions using pickle serialization.

    Pickle automatically handles the complex structures:
    - LMv3Response (dataclass)
    - SchematismPage (Pydantic model)
    - Nested structures (entries, BBox, etc.)

    No manual serialization/deserialization needed!
    """

    _item_type = LMv3Response
    _cache_type = "LMv3Cache"

    def __init__(self, checkpoint: str, caches_dir: Path | None = None):
        """Initialize LMv3 cache.

        Args:
            checkpoint: Model checkpoint identifier for cache namespacing.
                       Different checkpoints use separate cache directories.
            caches_dir: Optional custom cache directory path.
        """
        self.checkpoint = checkpoint
        super().__init__(
            cache_name=checkpoint,
            caches_dir=caches_dir,
            size_limit=2 * 1024 * 1024 * 1024,
        )

    def _get_logging_context(self) -> dict[str, object]:
        return {"checkpoint": self.checkpoint}

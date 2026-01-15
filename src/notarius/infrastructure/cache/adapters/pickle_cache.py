"""Generic PickleCache base class for type-safe caching with pickle serialization."""

import pickle
from abc import ABC
from pathlib import Path
from typing import TypeVar, cast, override

from structlog import get_logger

from notarius.application.ports.outbound.cache import BaseCache, SupportedCacheTypes
from notarius.shared.logger import Logger

logger: Logger = get_logger(__name__)

ItemT = TypeVar("ItemT")


class PickleCache[ItemT](BaseCache[ItemT], ABC):
    """Generic type-safe cache using pickle for automatic serialization.

    This base class handles all common cache operations:
    - Serialization/deserialization with pickle error handling
    - Logging of serialization failures
    - Key truncation for logging

    Subclasses must:
    1. Define `_item_type` class variable
    2. Define `_cache_type` class variable
    3. Implement __init__ with desired parameters
    4. Optionally override _get_logging_context() for extra context
    """

    _item_type: type[ItemT]
    _cache_type: SupportedCacheTypes
    _default_size_limit: int = 2 * 1024 * 1024 * 1024  # 2GB

    def __init__(
        self,
        cache_name: str,
        caches_dir: Path | None = None,
        size_limit: int | None = None,
    ):
        """Initialize the pickle cache.

        Args:
            cache_name: Name for this cache instance (used in directory path)
            caches_dir: Optional custom cache directory
            size_limit: Optional size limit in bytes (default: 2GB)
        """
        super().__init__(
            cache_name=cache_name,
            caches_dir=caches_dir,
            size_limit=size_limit or self._default_size_limit,
        )

    @property
    @override
    def cache_type(self) -> SupportedCacheTypes:
        return self._cache_type

    def _get_logging_context(self) -> dict[str, object]:
        """Get extra context for logging. Override in subclasses if needed."""
        return {}

    @override
    def get(self, key: str) -> ItemT | None:
        """Retrieve item from cache.

        Args:
            key: Cache key

        Returns:
            Cached item if found, None otherwise
        """
        try:
            raw_data = self.cache.get(key)
            if raw_data is None:
                return None
            return cast(ItemT, raw_data)
        except (pickle.PickleError, AttributeError, ImportError) as e:
            context = self._get_logging_context()
            logger.warning(
                "cache_deserialization_failed",
                key=key[:16],
                error=str(e),
                error_type=type(e).__name__,
                **context,
            )
            return None

    @override
    def set(self, key: str, value: ItemT) -> bool:
        """Store item in cache.

        Args:
            key: Cache key
            value: Item to cache

        Returns:
            True if cached successfully
        """
        try:
            return self.cache.set(key, value)
        except (pickle.PickleError, TypeError) as e:
            context = self._get_logging_context()
            logger.error(
                "cache_serialization_failed",
                key=key[:16],
                error=str(e),
                **context,
            )
            return False

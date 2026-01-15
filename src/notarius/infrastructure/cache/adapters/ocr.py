"""OCR cache adapter using pickle for automatic serialization."""

from pathlib import Path
from typing import TypedDict

from notarius.infrastructure.cache.adapters.pickle_cache import PickleCache
from notarius.infrastructure.ocr.engine_adapter import OCRResponse


class OCRCacheKeyParams(TypedDict, total=False):
    """Type definition for OCR cache key parameters."""

    image_hash: str


class PyTesseractCache(PickleCache[OCRResponse]):
    """Type-safe cache for PyTesseract OCR sample using pickle serialization.

    Pickle automatically handles the Pydantic models:
    - PyTesseractCacheItem
    - PyTesseractContent
    - BBox structures

    No manual serialization/deserialization needed!
    """

    _item_type = OCRResponse
    _cache_type = "PyTesseractCache"

    def __init__(
        self,
        language: str = "lat+pol+rus",
        caches_dir: Path | None = None,
    ):
        """Initialize PyTesseract cache.

        Args:
            language: Languages string passed to Tesseract. Used to create
                     separate cache directories for different language setups.
            caches_dir: Optional path overriding the default cache directory.
        """
        self.language = language
        super().__init__(
            cache_name=language,
            caches_dir=caches_dir,
            size_limit=2 * 1024 * 1024 * 1024,
        )

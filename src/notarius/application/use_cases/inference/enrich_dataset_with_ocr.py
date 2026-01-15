"""Refactored OCR use case using cached engine - EXAMPLE.

This shows how the use case becomes much simpler when caching is handled
at the engine level.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import final, override, cast


from notarius.application.use_cases.use_case import (
    BaseRequest,
    BaseResponse,
    AsyncBaseUseCase,
)
from notarius.infrastructure.ocr import OCREngine, OCRRequest, OCRMode
from notarius.infrastructure.ocr.types import SimpleOCRResult
from notarius.infrastructure.persistence.storage import ImageRepository
from notarius.schemas.data.pipeline import BaseDataset, BaseDataItem, BaseItemDataset
from notarius.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EnrichWithOCRRequest(BaseRequest):
    """Request to enrich dataset with OCR predictions."""

    dataset: BaseDataset[BaseDataItem]
    mode: OCRMode = "text"
    overwrite: bool = False


@dataclass
class EnrichWithOCRResponse(BaseResponse):
    """Response containing OCR-enriched dataset."""

    dataset: BaseDataset[BaseDataItem]
    processed_count: int


@final
class EnrichDatasetWithOCR(
    AsyncBaseUseCase[EnrichWithOCRRequest, EnrichWithOCRResponse]
):
    """
    Simplified use case for enriching a dataset with OCR text predictions.

    This refactored version no longer handles caching logic - that's now
    handled transparently by the CachedEngine wrapper.
    """

    def __init__(
        self,
        ocr_engine: OCREngine,
        image_storage: ImageRepository,
    ):
        """
        Initialize the use case.

        Args:
            ocr_engine: Engine for performing OCR predictions (may be cached)
            image_storage: Resource for loading images from storage
        """
        self.ocr_engine = ocr_engine
        self.image_storage = image_storage

    @override
    async def execute(self, request: EnrichWithOCRRequest) -> EnrichWithOCRResponse:
        """
        Execute the OCR enrichment workflow.

        The caching is now handled transparently by the engine if it's wrapped
        with CachedEngine.
        """
        dataset_len = len(request.dataset.items)
        new_dataset_items: list[BaseDataItem] = []
        processed_count = 0

        for i, item in enumerate(request.dataset.items):
            if not item.image_path:
                logger.debug(f"Skipping item {i}/{dataset_len} - no image_path")
                continue

            # Skip if already has text and not overwriting
            if item.text and not request.overwrite:
                new_dataset_items.append(item)
                continue
            image = self.image_storage.get(Path(item.image_path)).convert("RGB")
            logger.info(f"Processing {i + 1}/{dataset_len} sample with OCR.")

            ocr_request = OCRRequest(input=image, mode=request.mode)
            response = self.ocr_engine.process(ocr_request)
            processed_count += 1

            new_dataset_items.append(
                BaseDataItem(
                    image_path=item.image_path,
                    text=cast(SimpleOCRResult, response.output).text,
                    metadata=item.metadata,
                )
            )

        logger.info(
            "OCR enrichment completed",
            total_items=dataset_len,
            processed_count=processed_count,
        )

        return EnrichWithOCRResponse(
            dataset=BaseItemDataset(items=new_dataset_items),
            processed_count=processed_count,
        )

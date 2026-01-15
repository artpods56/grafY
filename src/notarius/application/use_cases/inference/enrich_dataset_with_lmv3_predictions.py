"""Use case for enriching dataset with LayoutLMv3 predictions.

Refactored version where caching is handled at the engine level,
not within the use case.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import final, override

from notarius.application.use_cases.use_case import (
    BaseRequest,
    BaseResponse,
    BaseUseCase,
)
from notarius.infrastructure.ml_models.lmv3.engine_adapter import (
    LMv3Engine,
    LMv3Request,
)
from notarius.infrastructure.persistence.storage import ImageRepository
from notarius.schemas.data.pipeline import (
    PredictionDataItem,
    PredictionItemDataset,
    BaseItemDataset,
)
from notarius.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EnrichWithLMv3Request(BaseRequest):
    """Request to enrich dataset with LayoutLMv3 predictions."""

    dataset: BaseItemDataset


@dataclass
class EnrichWithLMv3Response(BaseResponse):
    """Response containing LayoutLMv3-enriched dataset."""

    dataset: PredictionItemDataset
    processed_count: int


@final
class EnrichDatasetWithLMv3(BaseUseCase[EnrichWithLMv3Request, EnrichWithLMv3Response]):
    """
    Use case for enriching a dataset with LayoutLMv3 predictions.

    This refactored version no longer handles caching logic - that's now
    handled transparently by wrapping the engine before passing it in.
    """

    def __init__(
        self,
        lmv3_engine: LMv3Engine,
        image_storage: ImageRepository,
    ):
        """
        Initialize the use case.

        Args:
            lmv3_engine: Engine for performing LayoutLMv3 predictions (may be cached)
            image_storage: Resource for loading images from storage
        """
        self.lmv3_engine = lmv3_engine
        self.image_storage = image_storage

    @override
    def execute(self, request: EnrichWithLMv3Request) -> EnrichWithLMv3Response:
        """
        Execute the LayoutLMv3 enrichment workflow.

        The caching is now handled transparently by the engine if it's wrapped
        with CachedEngine.

        Args:
            request: Request containing dataset to enrich

        Returns:
            Response with enriched dataset and processing statistics
        """
        dataset_len = len(request.dataset.items)
        new_dataset_items: list[PredictionDataItem] = []
        processed_count = 0

        for i, item in enumerate(request.dataset.items):
            if not item.image_path:
                logger.debug(f"Skipping item {i}/{dataset_len} - no image_path")
                continue

            image = self.image_storage.get(Path(item.image_path)).convert("RGB")
            logger.info(f"Processing {i + 1}/{dataset_len} sample with LMv3.")

            lmv3_request = LMv3Request(input=image)
            response = self.lmv3_engine.process(lmv3_request)
            processed_count += 1

            new_dataset_items.append(
                PredictionDataItem(
                    image_path=item.image_path,
                    text=item.text,
                    predictions=response.output,
                    metadata=item.metadata,
                )
            )

        logger.info(
            "LayoutLMv3 enrichment completed",
            total_items=dataset_len,
            processed_count=processed_count,
        )

        return EnrichWithLMv3Response(
            dataset=PredictionItemDataset(items=new_dataset_items),
            processed_count=processed_count,
        )

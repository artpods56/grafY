"""Inference use cases for enriching datasets with model predictions."""

from notarius.application.use_cases.inference.enrich_dataset_with_ocr import (
    EnrichDatasetWithOCR,
    EnrichWithOCRRequest,
    EnrichWithOCRResponse,
)
from notarius.application.use_cases.inference.enrich_dataset_with_lmv3_predictions import (
    EnrichDatasetWithLMv3,
    EnrichWithLMv3Request,
    EnrichWithLMv3Response,
)
from notarius.application.use_cases.inference.enrich_dataset_with_ocr_using_llm import (
    EnrichDatasetWithLLMOCR,
    EnrichWithLLMOCRRequest,
    EnrichWithLLMOCRResponse,
)
from notarius.application.use_cases.inference.generate_source_dataset import (
    GenerateSourceDataset,
    GenerateSourceDatasetRequest,
    GenerateSourceDatasetResponse,
    SOURCE_GENERATION_CONTEXT_PROVIDERS,
)

__all__ = [
    "EnrichDatasetWithOCR",
    "EnrichWithOCRRequest",
    "EnrichWithOCRResponse",
    "EnrichDatasetWithLMv3",
    "EnrichWithLMv3Request",
    "EnrichWithLMv3Response",
    "EnrichDatasetWithLLMOCR",
    "EnrichWithLLMOCRRequest",
    "EnrichWithLLMOCRResponse",
    "GenerateSourceDataset",
    "GenerateSourceDatasetRequest",
    "GenerateSourceDatasetResponse",
    "SOURCE_GENERATION_CONTEXT_PROVIDERS",
]

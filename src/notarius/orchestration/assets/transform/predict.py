import random
from typing import cast

import dagster as dg
from dagster import AssetIn, AssetExecutionContext, MetadataValue

from notarius.application.services import (
    DatasetProcessor,
    ItemProcessor,
    TextOnlyRequestHandler,
    TextExtractionResponseHandler,
    StatelessStrategy,
    ComposedContextProvider,
)
from notarius.application.services.context.strategy import (
    get_context_strategy,
    ContextStrategySelection,
)

from notarius.application.services.message_builder import Jinja2MessageBuilder
from notarius.application.services.processors.item_processor import (
    StandardRequestHandler,
    PredictionsRefinementResponseHandler,
)
from notarius.application.use_cases.inference.refine_predictions_using_llm import (
    RefinePredictionsWithLLM,
    RefinePredictionsRequest,
    PREDICTIONS_REFINEMENT_CONTEXT_PROVIDERS,
)
from notarius.infrastructure.llm.prompt_manager import Jinja2PromptRenderer
from notarius.infrastructure.ocr.engine_adapter import OCRMode, OCREngine
from notarius.infrastructure.persistence.storage import ImageRepository
from notarius.orchestration.constants import (
    AssetLayer,
    ResourceGroup,
    DataSource,
    Kinds,
)
from notarius.orchestration.resources.base import (
    OCREngineResource,
    LMv3EngineResource,
    LLMEngineResource,
)
from notarius.orchestration.resources.storage import ImageRepositoryResource
from notarius.schemas.data.pipeline import (
    BaseDataset,
    BaseDataItem,
    PredictionItemDataset,
    PredictionDataItem,
)
from notarius.application.use_cases.inference.add_ocr_to_dataset import (
    EnrichWithOCRRequest,
    EnrichDatasetWithOCR,
)
from notarius.application.use_cases.inference.add_lmv3_preds_to_dataset import (
    EnrichDatasetWithLMv3,
    EnrichWithLMv3Request,
)
from notarius.application.use_cases.inference.enrich_dataset_with_ocr_using_llm import (
    EnrichDatasetWithLLMOCR,
    EnrichWithLLMOCRRequest,
)
from notarius.domain.entities.schematism import SchematismPage


class OcrConfig(dg.Config):
    mode: OCRMode = "text"
    language: str = "lat+pol+rus"
    enable_cache: bool = True


@dg.asset(
    key_prefix=[AssetLayer.STG, DataSource.HUGGINGFACE],
    group_name=ResourceGroup.DATA,
    kinds={
        Kinds.PYTHON,
        Kinds.PYDANTIC,
    },
    ins={
        "dataset": AssetIn(key="base__dataset__pydantic"),
    },
)
async def pred__ocr_enriched_dataset__pydantic(
    context: AssetExecutionContext,
    dataset: BaseDataset[BaseDataItem],
    images_repository: dg.ResourceParam[ImageRepository],
    ocr_engine: dg.ResourceParam[OCREngine],
):
    config = ocr_engine.config

    use_case = EnrichDatasetWithOCR(
        ocr_engine=ocr_engine,
        image_storage=images_repository,
        language=config.language,
        enable_cache=config.enable_cache,
    )

    request = EnrichWithOCRRequest(
        dataset=dataset,
        mode="text",
    )
    response = await use_case.execute(request)

    # Add Dagster metadata
    random_sample = response.dataset.items[
        random.randint(0, len(response.dataset.items) - 1)
    ]

    context.add_output_metadata(
        {
            "len": MetadataValue.int(len(response.dataset.items)),
            "random_sample": MetadataValue.json(
                {k: v for k, v in random_sample.model_dump().items() if k != "image"}
            ),
            "items_with_text": MetadataValue.int(
                len([item for item in response.dataset.items if item.text])
            ),
            "ocr_executions": MetadataValue.int(response.ocr_executions),
            "cache_hits": MetadataValue.int(response.cache_hits),
        }
    )

    return response.dataset


class LMv3Config(dg.Config):
    skip: bool = False
    checkpoint: str = "layoutlmv3_focalloss_4000"
    enable_cache: bool = True


@dg.asset(
    key_prefix=[AssetLayer.STG, DataSource.HUGGINGFACE],
    group_name=ResourceGroup.DATA,
    kinds={Kinds.PYTHON, Kinds.PYDANTIC},
    ins={
        "dataset": AssetIn(key="base__dataset__pydantic"),
    },
)
async def pred__lmv3_enriched_dataset__pydantic(
    context: AssetExecutionContext,
    dataset: BaseDataset[BaseDataItem],
    config: LMv3Config,
    images_repository: dg.ResourceParam[ImageRepository],
    lmv3_engine: LMv3EngineResource,
    ocr_engine: dg.ResourceParam[OCREngine],
) -> PredictionItemDataset:
    # Get the actual engine instance from the resource

    if config.skip:
        return PredictionItemDataset.from_base_dataset(dataset)

    lmv3_model = lmv3_engine.get_engine(ocr_engine)

    # Use new CachedEngine pattern
    use_case = EnrichDatasetWithLMv3(
        lmv3_engine=lmv3_model,
        image_storage=images_repository,
        checkpoint=config.checkpoint,
        enable_cache=config.enable_cache,
    )

    # Execute use case
    request = EnrichWithLMv3Request(
        dataset=dataset  # pyright: ignore[reportArgumentType]
    )  # FIXME: Resolve generics mismatch between EnrichWithLMv3Request and BaseDataset types
    response = use_case.execute(request)
    random_sample = dataset.items[random.randint(0, len(dataset.items) - 1)]

    context.add_asset_metadata(
        {
            "checkpoint": MetadataValue.text(config.checkpoint),
            "cache_enabled": MetadataValue.bool(config.enable_cache),
        }
    )

    context.add_output_metadata(
        {
            "len": MetadataValue.int(len(dataset.items)),
            "random_sample": MetadataValue.json(
                {k: v for k, v in random_sample.model_dump().items() if k != "image"}
            ),
            "lmv3_executions": MetadataValue.int(response.lmv3_executions),
            "cache_hits": MetadataValue.int(response.cache_hits),
        }
    )

    return response.dataset


class LLMConfig(dg.Config):
    model_name: str = "google/gemini-3-flash-preview"
    context_strategy: str = "sliding_window"
    task_name: str = "structured_extraction"
    enable_cache: bool = True
    group_by_schematism_name: bool = True


@dg.asset(
    key_prefix=[AssetLayer.STG, DataSource.HUGGINGFACE],
    group_name=ResourceGroup.DATA,
    kinds={Kinds.PYTHON, Kinds.PYDANTIC},
    ins={
        "merged_dataset": AssetIn(key="pred__merged_ocr_lmv3_dataset__pydantic"),
    },
)
async def pred__llm_enriched_dataset__pydantic(
    context: AssetExecutionContext,
    merged_dataset: PredictionItemDataset,
    config: LLMConfig,
    images_repository: dg.ResourceParam[ImageRepository],
    llm_engine_resource: LLMEngineResource,
):
    """Generate LLM predictions for each item in the lmv3_dataset.

    This asset takes the LMv3-enriched lmv3_dataset and uses an LLM to generate
    improved predictions, optionally using the LMv3 predictions as hints.
    """
    llm_engine = llm_engine_resource.get_engine(
        cached=config.enable_cache,
        images_repository=images_repository,
        model_name=config.model_name,
    )

    item_processor = ItemProcessor(
        llm_engine=llm_engine,
        request_handler=StandardRequestHandler(output_type=SchematismPage),
        response_handler=PredictionsRefinementResponseHandler[PredictionDataItem](),
    )

    message_builder = Jinja2MessageBuilder(
        prompt_renderer=Jinja2PromptRenderer(template_dir="prompts"),
        task_name=config.task_name,
    )

    context_strategy = get_context_strategy(
        strategy_literal=cast(ContextStrategySelection, config.context_strategy),
        message_builder=message_builder,
    )

    dataset_processor = DatasetProcessor(
        item_processor=item_processor,
        images_repository=images_repository,
        context_provider=PREDICTIONS_REFINEMENT_CONTEXT_PROVIDERS,
        context_strategy=context_strategy,
    )
    use_case = RefinePredictionsWithLLM(
        dataset_processor=dataset_processor,
    )

    request = RefinePredictionsRequest(
        dataset=merged_dataset,
        group_by_schematism_name=config.group_by_schematism_name,
    )

    response = await use_case.execute(request)

    context.add_asset_metadata(
        {
            "task_name": MetadataValue.text(config.task_name),
            "cache_enabled": MetadataValue.bool(config.enable_cache),
        }
    )

    random_sample = (
        random.choice(response.dataset.items).model_dump()
        if response.dataset.items
        else {}
    )

    context.add_output_metadata(
        {
            "len": MetadataValue.int(len(response.dataset.items)),
            "random_sample": MetadataValue.json(random_sample),
        }
    )

    return response.dataset


class EnrichWithOCRUsingLLMConfig(dg.Config):
    """Configuration for LLM-based OCR asset."""

    model_name: str = "google/gemini-3-flash-preview"
    task_name: str = "ocr"
    enable_cache: bool = True
    group_by_schematism_name: bool = True
    max_concurrent_async_requests: int = 10


@dg.asset(
    key_prefix=[AssetLayer.STG, DataSource.HUGGINGFACE],
    group_name=ResourceGroup.DATA,
    kinds={
        Kinds.PYTHON,
        Kinds.PYDANTIC,
    },
    ins={
        "dataset": AssetIn(key="base__dataset__pydantic"),
    },
)
async def pred__llm_ocr_enriched_dataset__pydantic(
    context: AssetExecutionContext,
    dataset: BaseDataset[BaseDataItem],
    config: EnrichWithOCRUsingLLMConfig,
    images_repository: dg.ResourceParam[ImageRepository],
    llm_engine_resource: LLMEngineResource,
):
    """Enrich dataset with OCR text using LLM vision capabilities.

    This asset takes a dataset with images and uses an LLM (e.g., via OpenRouter)
    to extract text with high-fidelity Markdown structural reconstruction.
    This is an alternative to Tesseract-based OCR for higher quality extraction.

    Uses DatasetProcessor with StatelessStrategy for parallel async processing.
    """
    llm_engine = llm_engine_resource.get_engine(
        cached=config.enable_cache,
        images_repository=images_repository,
        model_name=config.model_name,
    )

    item_processor = ItemProcessor(
        llm_engine=llm_engine,
        request_handler=TextOnlyRequestHandler(),
        response_handler=TextExtractionResponseHandler[BaseDataItem](),
    )

    message_builder = Jinja2MessageBuilder(
        prompt_renderer=Jinja2PromptRenderer(template_dir="prompts"),
        task_name=config.task_name,
    )

    context_strategy = StatelessStrategy(message_builder=message_builder)

    dataset_processor = DatasetProcessor(
        item_processor=item_processor,
        images_repository=images_repository,
        context_provider=ComposedContextProvider([]),  # Empty for OCR
        context_strategy=context_strategy,
    )

    use_case = EnrichDatasetWithLLMOCR(dataset_processor=dataset_processor)

    request = EnrichWithLLMOCRRequest(
        dataset=dataset,
        group_by_schematism_name=config.group_by_schematism_name,
        max_concurrent_requests=config.max_concurrent_async_requests,
    )
    response = await use_case.execute(request)

    context.add_asset_metadata(
        {"asset_config": MetadataValue.json(config.model_dump())}
    )

    return response.dataset

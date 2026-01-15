from types import MappingProxyType
from typing import Any

import dagster as dg

from notarius.infrastructure.config.constants import ConfigType, DatasetConfigSubtype
from notarius.infrastructure.config.manager import config_manager
from notarius.orchestration.assets.extract.ingest import raw__hf__dataset
from notarius.orchestration.assets.transform.preprocess import preprocessed__hf__dataset
from notarius.orchestration.assets.transform.transform import (
    pred__merged_ocr_parsed_dataset__pydantic,
    GroundTruthDatasetConfig,
    base__dataset__pydantic,
    gt__parsed_dataset__pydantic,
)

from notarius.orchestration.assets.transform.predict import (
    pred__llm_ocr_enriched_dataset__pydantic,
    EnrichWithOCRUsingLLMConfig,
)
from notarius.orchestration.assets.transform.source_generation import (
    ocr__exported_json,
    OcrExportConfig,
    source__generated_dataset__pydantic,
    source__exported_json,
    SourceExportConfig,
    GenerateSourceGroundTruthDatasetConfig,
)

_all_assets_with_configs = {}


"""
--- data ingestion ---
ingests the data into base dataset from huggingface
"""
_all_assets_with_configs.update(
    {
        raw__hf__dataset: {
            "config": config_manager.load_config_as_model(
                config_name="base_huggingface_config",
                config_type=ConfigType.DATASET,
                config_subtype=DatasetConfigSubtype.DEFAULT,
            ).model_dump()
        },
    }
)

"""
--- preprocessing ---
performs operations like filtering and mapping
"""
_all_assets_with_configs.update(
    {
        preprocessed__hf__dataset: None,
    }
)

"""
--- dataset split ---
base dataset is used for source generation
ground truth parsed dataset provides the Polish text to convert to Latin source
"""
_all_assets_with_configs.update(
    {
        base__dataset__pydantic: None,
        gt__parsed_dataset__pydantic: {
            "config": GroundTruthDatasetConfig(
                ground_truth_source="parsed"
            ).model_dump(),
        },
    }
)

"""
--- enhance with ocr using llm ---
enrich dataset with OCR text extraction using LLM
"""
_all_assets_with_configs.update(
    {
        pred__llm_ocr_enriched_dataset__pydantic: {
            "config": EnrichWithOCRUsingLLMConfig(
                task_name="ocr",
                max_concurrent_async_requests=20,
                enable_cache=True,
            ).model_dump()
        },
    }
)

"""
--- export ocr results ---
exports OCR results to JSON for backup and manual review
"""
_all_assets_with_configs.update(
    {
        ocr__exported_json: {
            "config": OcrExportConfig(
                group_by_schematism=True,
                pretty_print=True,
            ).model_dump()
        },
    }
)

"""
--- merge ocr with ground truth ---
combines OCR results with parsed ground truth dataset
"""
_all_assets_with_configs.update(
    {
        pred__merged_ocr_parsed_dataset__pydantic: None,
    }
)

"""
--- generate source ground truth ---
generates Latin source ground truth from Polish parsed text
exports results to JSON for manual review
"""
_all_assets_with_configs.update(
    {
        source__generated_dataset__pydantic: {
            "config": GenerateSourceGroundTruthDatasetConfig(
                enable_cache=True,
                window_size=5,
            ).model_dump()
        },
        source__exported_json: {
            "config": SourceExportConfig(
                group_by_schematism=True, pretty_print=True
            ).model_dump()
        },
    }
)
ALL_SOURCE_GENERATION_ASSETS_WITH_CONFIGS = MappingProxyType[
    dg.AssetsDefinition, dict[str, Any | None]
](_all_assets_with_configs)


source_generation_job = dg.define_asset_job(
    name="source_generation_pipeline",
    description=(
        "Generate Latin source dataset from Polish ground truth. "
        "Pipeline: HF ingestion → preprocessing → LLM OCR → source generation → JSON export. "
        "Exports results to JSON files for manual review before updating HuggingFace dataset."
    ),
    selection=dg.AssetSelection.assets(
        *ALL_SOURCE_GENERATION_ASSETS_WITH_CONFIGS.keys()
    ),
    config=dg.RunConfig(
        ops={
            asset.key.to_python_identifier(): config
            for asset, config in ALL_SOURCE_GENERATION_ASSETS_WITH_CONFIGS.items()
            if config is not None
        },
    ),
)

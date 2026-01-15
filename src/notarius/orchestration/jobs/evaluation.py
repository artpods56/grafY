from typing import Any

import dagster as dg
from types import MappingProxyType

from notarius.infrastructure.config.constants import ConfigType, DatasetConfigSubtype
from notarius.infrastructure.config.manager import config_manager
from notarius.orchestration.assets.extract.ingest import (
    raw__hf__dataset,
    raw__pdf__dataset,
    PdfToDatasetConfig,
)
from notarius.orchestration.assets.load.export import (
    eval__excel_export_parsed_dataframe__pandas,
    eval__excel_export_source_dataframe__pandas,
    eval__wandb_export_dataframe__pandas,
    WandBDataFrameExport,
    ParsedDataFrameExportConfig,
    pred__export_llm_enriched_dataset__json,
    PredsSourceExportConfig,
    SourceDataFrameExportConfig,
)
from notarius.orchestration.assets.transform.postprocess import (
    pred__parsed_dataset__pydantic,
    ParsingConfig,
    gt__aligned_parsed_dataset__pydantic,
    gt__aligned_source_dataset__pydantic,
    AlignmentConfig,
)
from notarius.orchestration.assets.transform.preprocess import (
    preprocessed__hf__dataset,
    PreprocessingConfig,
)
from notarius.orchestration.assets.transform.transform import (
    pred__merged_ocr_parsed_dataset__pydantic,
    GroundTruthDatasetConfig,
    base__dataset__pydantic,
    gt__parsed_dataset__pydantic,
    gt__source_dataset__pydantic,
    pred__merged_ocr_lmv3_dataset__pydantic,
    eval__aligned_source_dataframe__pandas,
    eval__aligned_parsed_dataframe__pandas,
)

from notarius.orchestration.assets.transform.predict import (
    pred__llm_ocr_enriched_dataset__pydantic,
    EnrichWithOCRUsingLLMConfig,
    pred__lmv3_enriched_dataset__pydantic,
    LMv3Config,
    pred__llm_enriched_dataset__pydantic,
    LLMConfig,
)


_all_assets_with_configs = {}


"""
--- data ingestion ---
ingests the data into base dataset from huggingface and pdf files
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
        raw__pdf__dataset: {"config": PdfToDatasetConfig().model_dump()},
    }
)

"""
--- dataset preprocessing ---
performs operations like filtering and mapping
"""
_all_assets_with_configs.update(
    {
        preprocessed__hf__dataset: {"config": PreprocessingConfig().model_dump()},
    }
)

"""
--- dataset split ---
base dataset is used by enrichment assets
ground truth datasets are used by evaluation assets
"""
_all_assets_with_configs.update(
    {
        base__dataset__pydantic: None,
        gt__parsed_dataset__pydantic: {
            "config": GroundTruthDatasetConfig(
                ground_truth_source="parsed"
            ).model_dump(),
        },
        gt__source_dataset__pydantic: {
            "config": GroundTruthDatasetConfig(
                ground_truth_source="source"
            ).model_dump()
        },
    }
)

"""
--- initial dataset enrichment ---
enrich separate datasets with orc and predictions
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
        pred__lmv3_enriched_dataset__pydantic: {"config": LMv3Config().model_dump()},
    }
)


"""
--- dataset transformations ---
merge ocr dataset with lmv3 predictions dataset
prepare dataset used for structured extraction
"""
_all_assets_with_configs.update(
    {pred__merged_ocr_lmv3_dataset__pydantic: {"config": None}}
)


"""
--- predictions refinement with llm ---
use llm to refine predictions dataset
"""
_all_assets_with_configs.update(
    {
        pred__llm_enriched_dataset__pydantic: {"config": LLMConfig().model_dump()},
    }
)


"""
--- predictions parsing ---
parsing predictions with lat-pl mappings
"""
_all_assets_with_configs.update(
    {
        pred__parsed_dataset__pydantic: {"config": ParsingConfig().model_dump()},
    }
)


"""
--- entries aligning ---
aligns ground truth with predictions
"""
_all_assets_with_configs.update(
    {
        gt__aligned_parsed_dataset__pydantic: {
            "config": AlignmentConfig(aligner_type="hungarian").model_dump()
        },
        gt__aligned_source_dataset__pydantic: {
            "config": AlignmentConfig(aligner_type="hungarian").model_dump()
        },
    }
)


"""
--- dataset flattening ---
flattens aligned datasets into single dataframe
"""
_all_assets_with_configs.update(
    {
        eval__aligned_source_dataframe__pandas: {"config": None},
        eval__aligned_parsed_dataframe__pandas: {"config": None},
    }
)


"""
--- results exporting ---
exports results to excel and wandb
"""
_all_assets_with_configs.update(
    {
        eval__excel_export_parsed_dataframe__pandas: {
            "config": ParsedDataFrameExportConfig(
                file_name="parsed_schematism_comp.xlsx"
            ).model_dump()
        },
        eval__excel_export_source_dataframe__pandas: {
            "config": SourceDataFrameExportConfig(
                file_name="source_schematism_comp.xlsx"
            ).model_dump()
        },
        eval__wandb_export_dataframe__pandas: {
            "config": WandBDataFrameExport().model_dump()
        },
        pred__export_llm_enriched_dataset__json: {
            "config": PredsSourceExportConfig().model_dump()
        },
    }
)


ALL_EVALUATION_ASSETS_WITH_CONFIGS = MappingProxyType[
    dg.AssetsDefinition, dict[str, Any | None]
](_all_assets_with_configs)

evaluation_job = dg.define_asset_job(
    name="evaluation_pipeline",
    description=(
        "Evaluate OCR and structured extraction models on ecclesiastical schematism dataset. "
        "Pipeline: HF/PDF ingestion → preprocessing → OCR enrichment → LMv3 predictions → "
        "LLM refinement → parsing → alignment → evaluation metrics export to Excel and WandB."
    ),
    selection=dg.AssetSelection.assets(*ALL_EVALUATION_ASSETS_WITH_CONFIGS.keys()),
    config=dg.RunConfig(
        ops={
            asset.key.to_python_identifier(): config
            for asset, config in ALL_EVALUATION_ASSETS_WITH_CONFIGS.items()
            if config is not None
        },
    ),
)

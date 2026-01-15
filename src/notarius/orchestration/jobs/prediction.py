from types import MappingProxyType
from typing import Any

import dagster as dg

from notarius.infrastructure.config.constants import ConfigType, DatasetConfigSubtype
from notarius.infrastructure.config.manager import config_manager
from notarius.orchestration.assets.extract.ingest import (
    raw__hf__dataset,
    raw__pdf__dataset,
    PdfToDatasetConfig,
)
from notarius.orchestration.assets.transform.preprocess import (
    preprocessed__hf__dataset,
    PreprocessingConfig,
)
from notarius.orchestration.assets.transform.transform import (
    base__dataset__pydantic,
    pred__parsed_dataframe__pandas,
    pred__source_dataframe__pandas,
    pred__merged_ocr_lmv3_dataset__pydantic,
)
from notarius.orchestration.assets.transform.predict import (
    pred__lmv3_enriched_dataset__pydantic,
    LMv3Config,
    pred__llm_enriched_dataset__pydantic,
    LLMConfig,
    pred__llm_ocr_enriched_dataset__pydantic,
    EnrichWithOCRUsingLLMConfig,
)
from notarius.orchestration.assets.transform.postprocess import (
    pred__parsed_dataset__pydantic,
    ParsingConfig,
)
from notarius.orchestration.assets.load.export import (
    pred__excel_export_parsed_dataframe__pandas,
    pred__excel_export_source_dataframe__pandas,
    PredictionDataFrameExport,
)

_all_assets_with_configs = {}


"""
--- data ingestion ---
ingests the data into base dataset from huggingface and optionally from PDF files
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
--- preprocessing ---
performs operations like filtering and mapping
"""
_all_assets_with_configs.update(
    {
        preprocessed__hf__dataset: {"config": PreprocessingConfig().model_dump()},
    }
)

"""
--- dataset split ---
base dataset is used for prediction
"""
_all_assets_with_configs.update(
    {
        base__dataset__pydantic: None,
    }
)

"""
--- model predictions ---
enrich dataset with LMv3 and LLM predictions
"""
_all_assets_with_configs.update(
    {
        pred__llm_ocr_enriched_dataset__pydantic: {
            "config": EnrichWithOCRUsingLLMConfig().model_dump()
        },
        pred__lmv3_enriched_dataset__pydantic: {"config": LMv3Config().model_dump()},
        pred__llm_enriched_dataset__pydantic: {"config": LLMConfig().model_dump()},
    }
)


"""
--- dataset merging ---
merges lmv3 predictions with ocr
"""
pred__merged_ocr_lmv3_dataset__pydantic
_all_assets_with_configs.update(
    {
        pred__merged_ocr_lmv3_dataset__pydantic: {"config": None},
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
--- dataset flattening ---
flattens prediction datasets into dataframes
"""
_all_assets_with_configs.update(
    {
        pred__parsed_dataframe__pandas: None,
        pred__source_dataframe__pandas: None,
    }
)

"""
--- results exporting ---
exports predictions to excel
"""
_all_assets_with_configs.update(
    {
        pred__excel_export_parsed_dataframe__pandas: {
            "config": PredictionDataFrameExport(
                file_name="parsed_predictions.xlsx"
            ).model_dump()
        },
        pred__excel_export_source_dataframe__pandas: {
            "config": PredictionDataFrameExport(
                file_name="source_predictions.xlsx"
            ).model_dump()
        },
    }
)

ALL_PREDICTION_ASSETS_WITH_CONFIGS = MappingProxyType[
    dg.AssetsDefinition, dict[str, Any | None]
](_all_assets_with_configs)


prediction_pipeline_job = dg.define_asset_job(
    name="prediction_pipeline",
    description=(
        "Complete end-to-end prediction pipeline without evaluation. "
        "Pipeline: HF ingestion → preprocessing → LMv3 predictions → "
        "LLM refinement → parsing → flattening → Excel export."
    ),
    selection=dg.AssetSelection.assets(*ALL_PREDICTION_ASSETS_WITH_CONFIGS.keys()),
    config=dg.RunConfig(
        ops={
            asset.key.to_python_identifier(): config
            for asset, config in ALL_PREDICTION_ASSETS_WITH_CONFIGS.items()
            if config is not None
        },
    ),
)

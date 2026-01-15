import dagster as dg

from notarius.domain.services.parser import Parser
from notarius.orchestration.hf_io_manager import HuggingFaceDatasetIOManager
from dagster import in_process_executor

from notarius.orchestration.jobs.evaluation import (
    ALL_EVALUATION_ASSETS_WITH_CONFIGS,
    evaluation_job,
)
from notarius.orchestration.resources.storage import (
    LocalStorageResource,
    ImageRepositoryResource,
)
from notarius.orchestration.resources.base import (
    OCREngineResource,
    LMv3EngineResource,
    LLMEngineResource,
    ExcelWriterResource,
    WandBRunResource,
)
from notarius.shared.constants import OUTPUTS_DIR
from datetime import datetime

from notarius.orchestration.jobs.prediction import (
    prediction_pipeline_job,
    ALL_PREDICTION_ASSETS_WITH_CONFIGS,
)
from notarius.orchestration.jobs.source_generation import (
    source_generation_job,
    ALL_SOURCE_GENERATION_ASSETS_WITH_CONFIGS,
)
from notarius.config import app_config

from dotenv import load_dotenv

_ = load_dotenv()


storage_resource = LocalStorageResource(storage_root=str(app_config.storage_root))
image_repository = ImageRepositoryResource(storage_resource=storage_resource)

ocr_engine_resource = OCREngineResource()
lmv3_engine_resource = LMv3EngineResource()
llm_engine_resource = LLMEngineResource()

defs = dg.Definitions(
    assets=[
        *ALL_SOURCE_GENERATION_ASSETS_WITH_CONFIGS.keys(),
        *ALL_EVALUATION_ASSETS_WITH_CONFIGS.keys(),
        *ALL_PREDICTION_ASSETS_WITH_CONFIGS.keys(),
    ],
    jobs=[
        prediction_pipeline_job,
        evaluation_job,
        source_generation_job,
    ],
    resources={
        "hf_dataset_io_manager": HuggingFaceDatasetIOManager(),
        "file_storage": storage_resource,
        # Explicitly bind the dependency for ImageRepositoryResource
        "images_repository": image_repository,
        "parser": Parser(),
        "ocr_engine": ocr_engine_resource,
        "lmv3_engine": lmv3_engine_resource,
        # FIX: Explicitly bind the dependency here
        # "lmv3_engine": lmv3_engine_resource,
        # FIX: Explicitly bind the dependency here
        "llm_engine_resource": llm_engine_resource,
        "excel_writer": ExcelWriterResource(writing_path=str(OUTPUTS_DIR)),
        "wandb_run": WandBRunResource(
            project_name="KUL_IDUB_EcclesiaSchematisms",
            run_name=f"dagster_eval_{datetime.now().isoformat()}",
            mode="online",
        ),
    },
    executor=in_process_executor,
)

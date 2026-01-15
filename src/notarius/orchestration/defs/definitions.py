from datetime import datetime

import dagster as dg
import weave
from dagster import in_process_executor

from notarius.infrastructure.persistence.storage.local import LocalFileStorage

from notarius.domain.services.parser import Parser
from notarius.infrastructure.config.manager import get_config_manager
from notarius.shared.constants import TMP_DIR, OUTPUTS_DIR


from notarius.orchestration.jobs.exporting import exporting_assets, exporting_job
from notarius.orchestration.jobs.ingestion import (
    ingestion_assets,
    ingestion_job,
)
from notarius.orchestration.jobs.postprocessing import (
    postprocessing_assets,
    postprocessing_job,
)
from notarius.orchestration.jobs.prediction import (
    models_config_assets,
    prediction_assets,
    prediction_job,
)
from notarius.orchestration.jobs.complete_pipeline import complete_pipeline_job
from notarius.orchestration.pipelines.source_generation import (
    source_generation_assets,
    source_generation_job,
)
# TODO: Re-enable when pdf_pipeline is implemented
# https://github.com/anomalyco/KUL_IDUB_EcclesialSchematisms/issues/X
# from notarius.orchestration.jobs.pdf_pipeline import (
#     pdf_ingestion_assets,
#     pdf_ingestion_job,
# )

from notarius.orchestration.resources.base import (
    ExcelWriterResource,
    WandBRunResource,
    OCREngineResource,
    LMv3EngineResource,
    LLMEngineResource,
    WeaveResource,
    PdfFilesResource,
)
from notarius.orchestration.resources.storage import ImageRepositoryResource
from notarius.orchestration.hf_io_manager import hf_dataset_io_manager
from notarius.orchestration.dill_io_manager import dill_io_manager

from notarius.config import app_config

from dotenv import load_dotenv

_ = load_dotenv()
# Initialize Weave BEFORE any OpenAI clients are created
# This patches the OpenAI SDK for automatic tracing
weave.init("KUL_IDUB_EcclesiaSchematisms")


print(app_config)

file_storage = LocalFileStorage(app_config.storage_root)


defs = dg.Definitions(
    assets=[
        # ingestion
        *ingestion_assets,
        # configs
        *models_config_assets,
        # prediction
        *prediction_assets,
        # postprocessing
        *postprocessing_assets,
        # export
        *exporting_assets,
        # source generation
        *source_generation_assets,
    ],
    jobs=[
        ingestion_job,
        prediction_job,
        postprocessing_job,
        exporting_job,
        complete_pipeline_job,
        source_generation_job,
    ],
    resources={
        "file_storage": file_storage,
        "images_repository": ImageRepositoryResource(storage_resource=file_storage),
        "pdf_files": PdfFilesResource(),
        "config_manager": get_config_manager(),
        "parser": Parser(),
        "io_manager": dill_io_manager(base_dir=str(TMP_DIR / "dagster_dill_storage")),
        "hf_dataset_io_manager": hf_dataset_io_manager(
            base_dir=str(TMP_DIR / "dagster_hf_storage")
        ),
        "excel_writer": ExcelWriterResource(writing_path=str(OUTPUTS_DIR)),
        "wandb_run": WandBRunResource(
            project_name="KUL_IDUB_EcclesiaSchematisms",
            run_name=f"dagster_eval_{datetime.now().isoformat()}",
            mode="online",
        ),
        "weave_run": WeaveResource(),
        # ML Engines
        "ocr_engine": OCREngineResource(),
        "lmv3_engine": LMv3EngineResource(ocr_engine=OCREngineResource()),
        "llm_engine_resource": LLMEngineResource(),
    },
    executor=in_process_executor,
)

import dagster as dg

from dagster_graphql import DagsterGraphQLClient

from notarius.config import DagsterConfig
from notarius.infrastructure.llm.utils import parse_model_name
from notarius.orchestration.assets.extract.ingest import (
    raw__pdf__dataset,
    PdfToDatasetConfig,
)
from notarius.orchestration.assets.load.export import (
    eval__excel_export_parsed_dataframe__pandas,
    eval__excel_export_source_dataframe__pandas,
    pred__export_llm_enriched_dataset__json,
    ParsedDataFrameExportConfig,
    SourceDataFrameExportConfig,
    PredsSourceExportConfig,
)
from notarius.orchestration.assets.transform.predict import (
    pred__llm_enriched_dataset__pydantic,
    LLMConfig,
    pred__lmv3_enriched_dataset__pydantic,
    LMv3Config,
)
from notarius.orchestration.assets.transform.preprocess import (
    PreprocessingConfig,
    preprocessed__hf__dataset,
)

from notarius.orchestration.jobs.evaluation import (
    ALL_EVALUATION_ASSETS_WITH_CONFIGS,
)

from notarius.orchestration.constants import JobType, Environment

from notarius.shared.logger import get_logger

logger = get_logger(__name__)

dagster_config = DagsterConfig()

client = DagsterGraphQLClient(
    hostname=dagster_config.host, port_number=dagster_config.port
)

MODELS = [
    # "qwen/qwen3-vl-30b-a3b-instruct", # run and will finish, will not, lol
    # "qwen/qwen3-vl-8b-thinking", # not working, probably due to no structured output support
    # "baidu/ernie-4.5-vl-28b-a3b", # does not support structured output
    # "mistralai/mistral-medium-3.1",
    # "amazon/nova-pro-v1", # failed to produce structured output
    # "nvidia/nemotron-nano-12b-v2-vl:free",
    # "thudm/glm-4.1v-9b-thinking",
    # "stepfun-ai/step3", # throws exception for some reason
    # vVv working models vVv
    "google/gemini-3-flash-preview",  # our best friend
    # "google/gemma-3-12b-it",  # going strong
    # "bytedance-seed/seed-1.6-flash"  # testing
    # "z-ai/glm-4.6v" # fails to generate structured output, would need json healing
    # "qwen/qwen3-vl-32b-instruct",  # testing
]

# FILTERED_SCHEMATISMS = ["tarnow_1870"]
FILTERED_SCHEMATISMS = [
    "chelmno_1871",
    "chelmno_1904",
    "chelmno_1938",
    "chelmno_1939",
    "czestochowa_1937",
    "czestochowa_1939",
    "gniezno_1870",
    "gniezno_1890",
    "gniezno_1936",
    "gniezno_1938",
    "kielce_1872",
    "kielce_1874",
    "kielce_1938",
    "kielce_1939",
    "krakow_1871",
    "krakow_1872",
    "krakow_1938",
    "krakow_1939",
    "kretosz_1986",
    "liber_crac_1529",
    "lodz_1938",
    "lodz_1939",
    "lomza_1938",
    "lomza_1939",
    "lublin_1870",
    "lublin_1871",
    "lublin_1938",
    "lublin_1939",
    "luck_1872",
    "luck_1873",
    "luck_1937",
    "luck_1938",
    "lwow_1871",
    "lwow_1877",
    "lwow_1936",
    "lwow_1938",
    "pinsk_1938",
    "pinsk_1939",
    "pirawski",
    "plock_1880",
    "plock_1882",
    "plock_1938",
    "plock_1939",
    "podlasie_1938",
    "podlasie_1939",
    "przemysl_1869",
    "przemysl_1874",
    "przemysl_1937",
    "przemysl_1938",
    "sandomierz_1874",
    "sandomierz_1938",
    "sandomierz_1939",
    "sejny_1874",
    "sejny_1877",
    "slask_1936",
    "slask_1938",
    "tarnow_1871",
    "tarnow_1938",
    "tarnow_1939",
    "warmia_1871",
    "warmia_1872",
    "warszawa_1870",
    "warszawa_1872",
    "warszawa_1938",
    "warszawa_1939",
    "wilno_1870",
    "wilno_1874",
    "wilno_1938",
    "wilno_1939",
    "wloclawek_1872",
    "wloclawek_1938",
    "wloclawek_1939",
    "zmudz_1863",
    "zmudz_1873",
]
USE_LMV3_MODEL = False


def main():

    for model in MODELS:

        run_config = ALL_EVALUATION_ASSETS_WITH_CONFIGS.copy()

        run_config.update(
            {
                preprocessed__hf__dataset: {
                    "config": PreprocessingConfig(
                        filtered_schematisms=FILTERED_SCHEMATISMS
                    ).model_dump()
                },
                raw__pdf__dataset: {"config": PdfToDatasetConfig().model_dump()},
            }
        )

        run_config.update(
            {
                pred__lmv3_enriched_dataset__pydantic: {
                    "config": LMv3Config(skip=not USE_LMV3_MODEL).model_dump()
                },
            }
        )

        run_config.update(
            {
                pred__llm_enriched_dataset__pydantic: {
                    "config": LLMConfig(model_name=model).model_dump()
                }
            }
        )

        run_config.update(
            {
                eval__excel_export_parsed_dataframe__pandas: {
                    "config": ParsedDataFrameExportConfig(
                        file_name=f"{parse_model_name(model)}_parsed_schematism_comp.xlsx"
                    ).model_dump()
                },
                eval__excel_export_source_dataframe__pandas: {
                    "config": SourceDataFrameExportConfig(
                        file_name=f"{parse_model_name(model)}_source_schematism_comp.xlsx"
                    ).model_dump()
                },
                pred__export_llm_enriched_dataset__json: {
                    "config": PredsSourceExportConfig(
                        filename_prefix=f"predictions_{parse_model_name(model)}"
                    ).model_dump()
                },
            }
        )

        run_id = client.submit_job_execution(
            job_name="evaluation_pipeline",
            run_config=dg.RunConfig(
                ops={
                    asset.key.to_python_identifier(): config
                    for asset, config in run_config.items()
                    if config is not None
                },
            ),
            tags={
                "environment": Environment.DEV,
                "task": JobType.EVALUATION,
                "model": model,
                "lmv3_used": USE_LMV3_MODEL,
                **{
                    schematism_name: ""
                    for schematism_name in FILTERED_SCHEMATISMS  # assigns labels based on filtered schematisms
                },
            },
        )

        logger.info(f"Submitted run for {model}: {run_id}")


if __name__ == "__main__":
    main()

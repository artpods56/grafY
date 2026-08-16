import pytest
from pydantic import ValidationError

from grafy_agent_worker.settings import AgentWorkerSettings


@pytest.mark.parametrize(
    "field_name",
    ("executor_max_request_bytes", "executor_max_response_bytes"),
)
def test_executor_payload_limits_cannot_exceed_sandbox_output_limit(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError):
        AgentWorkerSettings.model_validate(
            {
                field_name: 16_777_217,
            }
        )


def test_executor_admission_settings_are_explicit_and_bounded() -> None:
    settings = AgentWorkerSettings.model_validate(
        {
            "executor_max_concurrent_executions": 7,
            "executor_max_queued_executions": 11,
            "executor_admission_timeout_seconds": 0.25,
        }
    )

    assert settings.executor_max_concurrent_executions == 7
    assert settings.executor_max_queued_executions == 11
    assert settings.executor_admission_timeout_seconds == 0.25

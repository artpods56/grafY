import pytest

from grafy_agent.errors import AgentConfigurationError
from grafy_agent.pydantic_ai_agent import CodingAgentSettings, PydanticAICodingAgent


def test_pydantic_ai_agent_fails_closed_without_model_provider_configuration() -> None:
    with pytest.raises(AgentConfigurationError, match="GRAFY_AGENT_MODEL"):
        PydanticAICodingAgent(CodingAgentSettings(model=None, openrouter_api_key=None))

    with pytest.raises(
        AgentConfigurationError,
        match="GRAFY_AGENT_OPENROUTER_API_KEY",
    ):
        PydanticAICodingAgent(
            CodingAgentSettings(model="openai/gpt-5", openrouter_api_key=None)
        )

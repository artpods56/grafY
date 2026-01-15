import os
from typing import final, override

from openai import OpenAI, AsyncOpenAI, APIConnectionError
from pydantic import BaseModel
from pydantic_core import ValidationError

from notarius.application.ports.outbound.llm_provider import LLMProvider
from notarius.domain.entities.messages import ChatMessageList
from notarius.infrastructure.llm.providers.openai_provider.completions import (
    OpenAIResponse,
)
from notarius.infrastructure.llm.providers.openai_provider.translator import (
    messages_to_openai,
)
from notarius.schemas.configs.llm_model_config import ClientConfig
from notarius.shared.logger import get_logger


logger = get_logger(__name__)


@final
class OpenAICompatibleProvider(LLMProvider[OpenAI]):
    """Concrete implementation for OpenAI-compatible APIs.

    This adapter translates domain types to OpenAI-specific formats,
    allowing the rest of the application to remain provider-agnostic.
    """

    def __init__(self, config: ClientConfig):
        super().__init__(config)
        self._async_client: AsyncOpenAI | None = None

    def _get_api_key(self) -> str:
        """Get API key from environment."""
        api_key_env_var = self.config.api_key_env_var
        if not api_key_env_var:
            raise ValueError(
                "api_key_env_var must be set in the OpenAI provider config."
            )
        api_key = os.environ.get(api_key_env_var)
        if not api_key:
            raise ValueError(f"Environment variable {api_key_env_var} is not set.")
        return api_key

    @override
    def _initialize_client(self) -> OpenAI:
        """Initialize the sync OpenAI client."""
        return OpenAI(api_key=self._get_api_key(), base_url=self.config.base_url)

    @property
    def async_client(self) -> AsyncOpenAI:
        """Lazy-initialize async client."""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self._get_api_key(),
                base_url=self.config.base_url,
            )
        return self._async_client

    @override
    def generate_response[ResponseT: BaseModel](
        self,
        messages: ChatMessageList,
        text_format: type[ResponseT] | None = None,
    ) -> OpenAIResponse[ResponseT]:
        """Generate a output using OpenAI's API.

        Args:
            messages: Domain message list
            text_format: Optional Pydantic model for structured output

        Returns:
            OpenAIResponse wrapping the provider's output

        Raises:
            APIConnectionError: If connection to OpenAI fails
        """
        try:
            openai_messages = messages_to_openai(messages)

            if text_format:
                try:
                    response = self.client.responses.parse(
                        model=self.config.model,
                        input=openai_messages,
                        text_format=text_format,
                        temperature=self.config.params.temperature,
                        top_p=self.config.params.top_p,
                    )
                except ValidationError as e:
                    logger.warning(
                        "Structured output validation failed inside OpenAI SDK",
                        error=str(e),
                    )
                    return OpenAIResponse(
                        structured_response=None,
                        text_response=None,  # or stash raw text if available
                    )

                return OpenAIResponse[ResponseT](
                    structured_response=response.output_parsed, text_response=None
                )
            else:
                response = self.client.responses.create(
                    model=self.config.model,
                    input=openai_messages,
                )

                return OpenAIResponse[ResponseT](
                    structured_response=None, text_response=response.output_text
                )

        except APIConnectionError as e:
            logger.error(f"Connection error while generating output from OpenAI: {e}")
            raise

    @override
    async def generate_response_async[ResponseT: BaseModel](
        self,
        messages: ChatMessageList,
        text_format: type[ResponseT] | None = None,
    ) -> OpenAIResponse[ResponseT]:
        """Generate a response using OpenAI's async API.

        Args:
            messages: Domain message list
            text_format: Optional Pydantic model for structured output

        Returns:
            OpenAIResponse wrapping the provider's output

        Raises:
            APIConnectionError: If connection to OpenAI fails
        """
        try:
            openai_messages = messages_to_openai(messages)

            if text_format:
                response = await self.async_client.responses.parse(
                    model=self.config.model,
                    input=openai_messages,
                    text_format=text_format,
                    temperature=self.config.params.temperature,
                    top_p=self.config.params.top_p,
                )
                return OpenAIResponse[ResponseT](
                    structured_response=response.output_parsed,
                    text_response=None,
                )
            else:
                response = await self.async_client.responses.create(
                    model=self.config.model,
                    input=openai_messages,
                )
                return OpenAIResponse[ResponseT](
                    structured_response=None,
                    text_response=response.output_text,
                )

        except APIConnectionError as e:
            logger.error(f"Async connection error while generating output: {e}")
            raise

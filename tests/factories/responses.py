"""Factories for creating response objects.

This module provides factories for creating response DTOs from engines and use cases.
"""

from dataclasses import dataclass
from pydantic import BaseModel

from tests.factories.base import BaseFactory
from tests.factories.datasets import BaseDatasetFactory, PredictionDatasetFactory
from tests.factories.entities import SchematismPageFactory
from tests.factories.messages import ConversationFactory
from notarius.application.use_cases.inference.enrich_dataset_with_ocr import (
    EnrichWithOCRResponse,
)
from notarius.application.use_cases.inference.enrich_dataset_with_lmv3_predictions import (
    EnrichWithLMv3Response,
)
from notarius.application.use_cases.ingestion.ingest_documents_from_pdf import (
    IngestPDFResponse,
)
from notarius.infrastructure.ocr.engine_adapter import OCRResponse
from notarius.infrastructure.ocr.types import (
    SimpleOCRResult,
    StructuredOCRResult,
    OCRResult,
)
from notarius.infrastructure.ml_models.lmv3.engine_adapter import LMv3Response
from notarius.infrastructure.llm.engine_adapter import CompletionResult
from notarius.domain.entities.completions import BaseProviderResponse
from notarius.domain.entities.schematism import SchematismPage
from notarius.infrastructure.llm.conversation import Conversation
from notarius.schemas.data.pipeline import BaseItemDataset, PredictionItemDataset
from notarius.schemas.data.structs import BBox


class SimpleOCRResultFactory(BaseFactory[SimpleOCRResult]):
    """Factory for creating SimpleOCRResult instances."""

    @classmethod
    def build(cls, text: str | None = None, **kwargs) -> SimpleOCRResult:
        """Build a SimpleOCRResult instance.

        Args:
            text: The OCR text
            **kwargs: Additional fields

        Returns:
            A new SimpleOCRResult instance

        Example:
            result = SimpleOCRResultFactory.build()
            result = SimpleOCRResultFactory.build(text="Sample OCR text")
        """
        return SimpleOCRResult(text=text or "Sample OCR text from factory", **kwargs)


class StructuredOCRResultFactory(BaseFactory[StructuredOCRResult]):
    """Factory for creating StructuredOCRResult instances."""

    @classmethod
    def build(
        cls,
        words: list[str] | None = None,
        bboxes: list[BBox] | None = None,
        word_count: int = 5,
        **kwargs,
    ) -> StructuredOCRResult:
        """Build a StructuredOCRResult instance.

        Args:
            words: List of words
            bboxes: List of bounding boxes (0-1000 normalized range)
            word_count: Number of words/boxes to generate if not provided
            **kwargs: Additional fields

        Returns:
            A new StructuredOCRResult instance

        Example:
            result = StructuredOCRResultFactory.build()
            result = StructuredOCRResultFactory.build(
                words=["Hello", "World"],
                bboxes=[(100, 100, 200, 150), (250, 100, 350, 150)]
            )
        """
        if words is None:
            words = [f"Word{i}" for i in range(word_count)]

        if bboxes is None:
            # Generate simple bounding boxes (0-1000 range)
            bboxes = [
                (100 + i * 150, 100, 200 + i * 150, 150) for i in range(len(words))
            ]

        return StructuredOCRResult(words=words, bboxes=bboxes, **kwargs)


class OCRResponseFactory(BaseFactory[OCRResponse]):
    """Factory for creating OCRResponse instances."""

    @classmethod
    def build(
        cls, output: OCRResult | None = None, mode: str = "text", **kwargs
    ) -> OCRResponse:
        """Build an OCRResponse instance.

        Args:
            output: OCR result (SimpleOCRResult or StructuredOCRResult)
            mode: Which type to create if output not provided ("text" or "structured")
            **kwargs: Additional fields to pass to the result factory
        """
        if output is None:
            if mode == "structured":
                output = StructuredOCRResultFactory.build(**kwargs)
            else:
                output = SimpleOCRResultFactory.build(**kwargs)

        return OCRResponse(output=output)

    @classmethod
    def build_with_text(cls, text: str) -> OCRResponse:
        """Build response with specific text.

        Args:
            text: The OCR text

        Returns:
            An OCRResponse with SimpleOCRResult

        Example:
            response = OCRResponseFactory.build_with_text("Sample text")
        """
        return cls.build(output=SimpleOCRResultFactory.build(text=text))


class LMv3ResponseFactory(BaseFactory[LMv3Response]):
    """Factory for creating LMv3Response instances."""

    @classmethod
    def build(cls, output: SchematismPage | None = None, **kwargs) -> LMv3Response:
        """Build an LMv3Response instance.

        Args:
            output: SchematismPage with predictions
            **kwargs: Additional fields

        Returns:
            A new LMv3Response instance

        Example:
            response = LMv3ResponseFactory.build()
            response = LMv3ResponseFactory.build(
                output=SchematismPageFactory.build(entry_count=10)
            )
        """
        if output is None:
            output = SchematismPageFactory.build()

        return LMv3Response(output=output, **kwargs)


@dataclass(frozen=True)
class FakeProviderResponse[T: BaseModel](BaseProviderResponse[T]):
    """Concrete implementation of BaseProviderResponse for testing."""

    pass


class BaseProviderResponseFactory(BaseFactory[BaseProviderResponse]):
    """Factory for creating BaseProviderResponse instances."""

    @classmethod
    def build(
        cls,
        structured_response: BaseModel | None = None,
        text_response: str | None = None,
        **kwargs,
    ) -> BaseProviderResponse:
        """Build a BaseProviderResponse instance.

        Args:
            structured_response: Structured Pydantic response
            text_response: Text response
            **kwargs: Additional fields

        Returns:
            A new FakeProviderResponse instance

        Example:
            response = BaseProviderResponseFactory.build()
            response = BaseProviderResponseFactory.build(text_response="Hello")
        """
        return FakeProviderResponse(
            structured_response=structured_response,
            text_response=text_response or "Sample LLM response from factory",
            **kwargs,
        )

    @classmethod
    def build_with_structured[T: BaseModel](
        cls, structured_response: T
    ) -> BaseProviderResponse[T]:
        """Build response with structured output.

        Args:
            structured_response: The structured Pydantic model

        Returns:
            A BaseProviderResponse with structured output

        Example:
            response = BaseProviderResponseFactory.build_with_structured(
                MySchema(field="value")
            )
        """
        return FakeProviderResponse(
            structured_response=structured_response, text_response=None
        )


class CompletionResultFactory(BaseFactory[CompletionResult]):
    """Factory for creating CompletionResult instances."""

    @classmethod
    def build(
        cls,
        output: BaseProviderResponse | None = None,
        conversation: Conversation | None = None,
        structured_output_expected: bool = False,
        **kwargs,
    ) -> CompletionResult:
        """Build a CompletionResult instance.

        Args:
            output: The provider response
            conversation: The conversation history
            structured_output_expected: Whether structured output was expected
            **kwargs: Additional fields

        Returns:
            A new CompletionResult instance

        Example:
            result = CompletionResultFactory.build()
            result = CompletionResultFactory.build(
                output=BaseProviderResponseFactory.build(text_response="Hi"),
                conversation=ConversationFactory.build()
            )
        """
        if output is None:
            output = BaseProviderResponseFactory.build()

        if conversation is None:
            conversation = ConversationFactory.build()

        return CompletionResult(
            output=output,
            conversation=conversation,
            structured_output_expected=structured_output_expected,
            **kwargs,
        )

    @classmethod
    def build_with_structured[T: BaseModel](
        cls, structured_response: T, conversation: Conversation | None = None
    ) -> CompletionResult[T]:
        """Build result with structured output.

        Args:
            structured_response: The structured response
            conversation: The conversation history

        Returns:
            A CompletionResult with structured output

        Example:
            result = CompletionResultFactory.build_with_structured(
                MySchema(field="value")
            )
        """
        output = BaseProviderResponseFactory.build_with_structured(structured_response)
        if conversation is None:
            conversation = ConversationFactory.build()

        return CompletionResult(
            output=output, conversation=conversation, structured_output_expected=True
        )


class EnrichWithOCRResponseFactory(BaseFactory[EnrichWithOCRResponse]):
    """Factory for creating EnrichWithOCRResponse instances."""

    @classmethod
    def build(
        cls,
        dataset: BaseItemDataset | None = None,
        processed_count: int | None = None,
        **kwargs,
    ) -> EnrichWithOCRResponse:
        """Build an EnrichWithOCRResponse instance.

        Args:
            dataset: The enriched dataset
            processed_count: Number of items processed (defaults to dataset size)
            **kwargs: Additional fields

        Returns:
            A new EnrichWithOCRResponse instance

        Example:
            response = EnrichWithOCRResponseFactory.build()
            response = EnrichWithOCRResponseFactory.build(
                dataset=BaseDatasetFactory.build(items=10),
                processed_count=10
            )
        """
        if dataset is None:
            dataset = BaseDatasetFactory.build()

        if processed_count is None:
            processed_count = len(dataset.items)

        return EnrichWithOCRResponse(
            dataset=dataset,
            processed_count=processed_count,
            **kwargs,
        )


class EnrichWithLMv3ResponseFactory(BaseFactory[EnrichWithLMv3Response]):
    """Factory for creating EnrichWithLMv3Response instances."""

    @classmethod
    def build(
        cls,
        dataset: PredictionItemDataset | None = None,
        processed_count: int | None = None,
        **kwargs,
    ) -> EnrichWithLMv3Response:
        """Build an EnrichWithLMv3Response instance.

        Args:
            dataset: The enriched prediction dataset
            processed_count: Number of items processed (defaults to dataset size)
            **kwargs: Additional fields

        Returns:
            A new EnrichWithLMv3Response instance

        Example:
            response = EnrichWithLMv3ResponseFactory.build()
            response = EnrichWithLMv3ResponseFactory.build(
                dataset=PredictionDatasetFactory.build(items=5),
                processed_count=5
            )
        """
        if dataset is None:
            dataset = PredictionDatasetFactory.build()

        if processed_count is None:
            processed_count = len(dataset.items)

        return EnrichWithLMv3Response(
            dataset=dataset,
            processed_count=processed_count,
            **kwargs,
        )


class IngestPDFResponseFactory(BaseFactory[IngestPDFResponse]):
    """Factory for creating IngestPDFResponse instances.

    Example:
        # Build with default dataset
        response = IngestPDFResponseFactory.build()

        # Build with custom dataset
        dataset = BaseDatasetFactory.build(items=10)
        response = IngestPDFResponseFactory.build(dataset=dataset)

        # Build with specific number of items
        response = IngestPDFResponseFactory.build_with_items(5)
    """

    @classmethod
    def build(
        cls,
        dataset: BaseItemDataset | None = None,
        **kwargs,
    ) -> IngestPDFResponse:
        """Build an IngestPDFResponse.

        Args:
            dataset: The dataset containing ingested items
            **kwargs: Additional arguments for IngestPDFResponse

        Returns:
            IngestPDFResponse instance

        Example:
            response = IngestPDFResponseFactory.build()
        """
        if dataset is None:
            dataset = BaseDatasetFactory.build(items=2)

        return IngestPDFResponse(
            dataset=dataset,
            **kwargs,
        )

    @classmethod
    def build_with_items(cls, num_items: int) -> IngestPDFResponse:
        """Build an IngestPDFResponse with specific number of items.

        Args:
            num_items: Number of items in the dataset

        Returns:
            IngestPDFResponse with dataset containing num_items items

        Example:
            response = IngestPDFResponseFactory.build_with_items(10)
        """
        dataset = BaseDatasetFactory.build(items=num_items)
        return cls.build(dataset=dataset)

    @classmethod
    def build_empty(cls) -> IngestPDFResponse:
        """Build an IngestPDFResponse with empty dataset.

        Returns:
            IngestPDFResponse with empty dataset

        Example:
            response = IngestPDFResponseFactory.build_empty()
        """
        dataset = BaseDatasetFactory.build_empty()
        return cls.build(dataset=dataset)

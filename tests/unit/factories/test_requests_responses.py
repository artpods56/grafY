"""Tests for request and response factories."""

import pytest
from PIL import Image

from tests.factories.requests import (
    EnrichWithOCRRequestFactory,
    EnrichWithLMv3RequestFactory,
    OCRRequestFactory,
    LMv3RequestFactory,
    CompletionRequestFactory,
)
from tests.factories.responses import (
    SimpleOCRResultFactory,
    StructuredOCRResultFactory,
    OCRResponseFactory,
    LMv3ResponseFactory,
    BaseProviderResponseFactory,
    CompletionResultFactory,
    EnrichWithOCRResponseFactory,
    EnrichWithLMv3ResponseFactory,
)
from notarius.application.use_cases.inference.enrich_dataset_with_ocr import (
    EnrichWithOCRRequest,
    EnrichWithOCRResponse,
)
from notarius.application.use_cases.inference.enrich_dataset_with_lmv3_predictions import (
    EnrichWithLMv3Request,
    EnrichWithLMv3Response,
)
from notarius.infrastructure.ocr.engine_adapter import OCRRequest, OCRResponse
from notarius.infrastructure.ocr.types import SimpleOCRResult, StructuredOCRResult
from notarius.infrastructure.ml_models.lmv3.engine_adapter import (
    LMv3Request,
    LMv3Response,
)
from notarius.infrastructure.llm.engine_adapter import (
    CompletionRequest,
    CompletionResult,
)


class TestEnrichWithOCRRequestFactory:
    """Tests for EnrichWithOCRRequestFactory."""

    def test_build_creates_request_with_defaults(self):
        """Test that build() creates request with defaults."""
        request = EnrichWithOCRRequestFactory.build()

        assert isinstance(request, EnrichWithOCRRequest)
        assert request.dataset is not None
        assert len(request.dataset.items) > 0
        assert request.mode == "text"

    def test_build_with_custom_mode(self):
        """Test that build() accepts custom mode."""
        request = EnrichWithOCRRequestFactory.build(mode="structured")

        assert request.mode == "structured"


class TestEnrichWithLMv3RequestFactory:
    """Tests for EnrichWithLMv3RequestFactory."""

    def test_build_creates_request_with_defaults(self):
        """Test that build() creates request with defaults."""
        request = EnrichWithLMv3RequestFactory.build()

        assert isinstance(request, EnrichWithLMv3Request)
        assert request.dataset is not None
        assert len(request.dataset.items) > 0


class TestOCRRequestFactory:
    """Tests for OCRRequestFactory."""

    def test_build_creates_request_with_default_image(self):
        """Test that build() creates request with default image."""
        request = OCRRequestFactory.build()

        assert isinstance(request, OCRRequest)
        assert isinstance(request.input, Image.Image)
        assert request.mode == "text"

    def test_build_with_custom_image(self):
        """Test that build() accepts custom image."""
        img = Image.new("RGB", (1000, 800), color="red")
        request = OCRRequestFactory.build(input=img)

        assert request.input == img


class TestLMv3RequestFactory:
    """Tests for LMv3RequestFactory."""

    def test_build_creates_request_with_rgb_image(self):
        """Test that build() creates request with RGB image."""
        request = LMv3RequestFactory.build()

        assert isinstance(request, LMv3Request)
        assert isinstance(request.input, Image.Image)
        # Verify it's RGB (3 channels)
        assert request.input.mode == "RGB"


class TestCompletionRequestFactory:
    """Tests for CompletionRequestFactory."""

    def test_build_creates_request_with_defaults(self):
        """Test that build() creates request with defaults."""
        request = CompletionRequestFactory.build()

        assert isinstance(request, CompletionRequest)
        assert request.input is not None
        assert len(request.input.messages) > 0

    def test_build_with_structured_output(self):
        """Test that build() accepts structured_output."""
        from pydantic import BaseModel

        class MySchema(BaseModel):
            field: str

        request = CompletionRequestFactory.build(structured_output=MySchema)

        assert request.structured_output == MySchema

    def test_build_with_system_prompt(self):
        """Test that build_with_system_prompt() creates request with system message."""
        request = CompletionRequestFactory.build_with_system_prompt("You are helpful")

        assert len(request.input.messages) == 1
        assert request.input.messages[0].role == "system"


class TestSimpleOCRResultFactory:
    """Tests for SimpleOCRResultFactory."""

    def test_build_creates_result_with_default_text(self):
        """Test that build() creates result with default text."""
        result = SimpleOCRResultFactory.build()

        assert isinstance(result, SimpleOCRResult)
        assert result.text is not None

    def test_build_with_custom_text(self):
        """Test that build() accepts custom text."""
        result = SimpleOCRResultFactory.build(text="Custom OCR text")

        assert result.text == "Custom OCR text"


class TestStructuredOCRResultFactory:
    """Tests for StructuredOCRResultFactory."""

    def test_build_creates_result_with_defaults(self):
        """Test that build() creates result with defaults."""
        result = StructuredOCRResultFactory.build()

        assert isinstance(result, StructuredOCRResult)
        assert len(result.words) == 5  # default word_count
        assert len(result.bboxes) == 5

    def test_build_with_custom_word_count(self):
        """Test that build() respects word_count."""
        result = StructuredOCRResultFactory.build(word_count=10)

        assert len(result.words) == 10
        assert len(result.bboxes) == 10

    def test_build_with_custom_words_and_bboxes(self):
        """Test that build() accepts custom words and bboxes."""
        words = ["Hello", "World"]
        bboxes = [(100, 100, 200, 150), (250, 100, 350, 150)]
        result = StructuredOCRResultFactory.build(words=words, bboxes=bboxes)

        assert result.words == words
        assert result.bboxes == bboxes


class TestOCRResponseFactory:
    """Tests for OCRResponseFactory."""

    def test_build_creates_text_response_by_default(self):
        """Test that build() creates text response by default."""
        response = OCRResponseFactory.build()

        assert isinstance(response, OCRResponse)
        assert isinstance(response.output, SimpleOCRResult)

    def test_build_creates_structured_response(self):
        """Test that build() creates structured response when mode=structured."""
        response = OCRResponseFactory.build(mode="structured")

        assert isinstance(response.output, StructuredOCRResult)

    def test_build_with_text(self):
        """Test that build_with_text() creates response with specific text."""
        response = OCRResponseFactory.build_with_text("Sample text")

        assert isinstance(response.output, SimpleOCRResult)
        assert response.output.text == "Sample text"


class TestLMv3ResponseFactory:
    """Tests for LMv3ResponseFactory."""

    def test_build_creates_response_with_default_page(self):
        """Test that build() creates response with default page."""
        response = LMv3ResponseFactory.build()

        assert isinstance(response, LMv3Response)
        assert response.output is not None
        assert len(response.output.entries) > 0


class TestBaseProviderResponseFactory:
    """Tests for BaseProviderResponseFactory."""

    def test_build_creates_response_with_text(self):
        """Test that build() creates response with text."""
        response = BaseProviderResponseFactory.build()

        assert response.text_response is not None

    def test_build_with_structured(self):
        """Test that build_with_structured() creates response with structured output."""
        from pydantic import BaseModel

        class MySchema(BaseModel):
            field: str

        schema_instance = MySchema(field="value")
        response = BaseProviderResponseFactory.build_with_structured(schema_instance)

        assert response.structured_response == schema_instance
        assert response.text_response is None


class TestCompletionResultFactory:
    """Tests for CompletionResultFactory."""

    def test_build_creates_result_with_defaults(self):
        """Test that build() creates result with defaults."""
        result = CompletionResultFactory.build()

        assert isinstance(result, CompletionResult)
        assert result.output is not None
        assert result.conversation is not None

    def test_build_with_structured(self):
        """Test that build_with_structured() creates result with structured output."""
        from pydantic import BaseModel

        class MySchema(BaseModel):
            field: str

        schema_instance = MySchema(field="value")
        result = CompletionResultFactory.build_with_structured(schema_instance)

        assert result.output.structured_response == schema_instance
        assert result.structured_output_expected is True


class TestEnrichWithOCRResponseFactory:
    """Tests for EnrichWithOCRResponseFactory."""

    def test_build_creates_response_with_defaults(self):
        """Test that build() creates response with defaults."""
        response = EnrichWithOCRResponseFactory.build()

        assert isinstance(response, EnrichWithOCRResponse)
        assert response.dataset is not None
        assert response.processed_count == len(response.dataset.items)

    def test_build_with_custom_values(self):
        """Test that build() accepts custom values."""
        response = EnrichWithOCRResponseFactory.build(processed_count=8)

        assert response.processed_count == 8


class TestEnrichWithLMv3ResponseFactory:
    """Tests for EnrichWithLMv3ResponseFactory."""

    def test_build_creates_response_with_defaults(self):
        """Test that build() creates response with defaults."""
        response = EnrichWithLMv3ResponseFactory.build()

        assert isinstance(response, EnrichWithLMv3Response)
        assert response.dataset is not None
        assert response.processed_count == len(response.dataset.items)

    def test_build_with_custom_values(self):
        """Test that build() accepts custom values."""
        response = EnrichWithLMv3ResponseFactory.build(processed_count=5)

        assert response.processed_count == 5

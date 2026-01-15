"""Factories for creating use case request objects.

This module provides factories for creating request DTOs for various use cases.
"""

from PIL import Image
from pydantic import BaseModel

from tests.factories.base import BaseFactory
from tests.factories.datasets import BaseDatasetFactory, PredictionDatasetFactory
from tests.factories.messages import ConversationFactory
from notarius.application.use_cases.inference.enrich_dataset_with_ocr import (
    EnrichWithOCRRequest,
)
from notarius.application.use_cases.inference.enrich_dataset_with_lmv3_predictions import (
    EnrichWithLMv3Request,
)
from notarius.application.use_cases.ingestion.ingest_documents_from_pdf import (
    IngestPDFRequest,
)
from notarius.infrastructure.ocr.engine_adapter import OCRRequest, OCRMode
from notarius.infrastructure.ml_models.lmv3.engine_adapter import LMv3Request
from notarius.infrastructure.llm.engine_adapter import CompletionRequest
from notarius.infrastructure.llm.conversation import Conversation
from notarius.schemas.data.pipeline import BaseItemDataset, PredictionItemDataset


class EnrichWithOCRRequestFactory(BaseFactory[EnrichWithOCRRequest]):
    """Factory for creating EnrichWithOCRRequest instances."""

    @classmethod
    def build(
        cls, dataset: BaseItemDataset | None = None, mode: OCRMode = "text", **kwargs
    ) -> EnrichWithOCRRequest:
        """Build an EnrichWithOCRRequest instance.

        Args:
            dataset: The dataset to enrich
            mode: OCR mode ("text" or "structured")
            **kwargs: Additional fields

        Returns:
            A new EnrichWithOCRRequest instance

        Example:
            request = EnrichWithOCRRequestFactory.build()
            request = EnrichWithOCRRequestFactory.build(
                dataset=BaseDatasetFactory.build(items=10),
                mode="structured"
            )
        """
        if dataset is None:
            dataset = BaseDatasetFactory.build()

        return EnrichWithOCRRequest(dataset=dataset, mode=mode, **kwargs)


class EnrichWithLMv3RequestFactory(BaseFactory[EnrichWithLMv3Request]):
    """Factory for creating EnrichWithLMv3Request instances."""

    @classmethod
    def build(
        cls, dataset: BaseItemDataset | None = None, **kwargs
    ) -> EnrichWithLMv3Request:
        """Build an EnrichWithLMv3Request instance.

        Args:
            dataset: The dataset to enrich
            **kwargs: Additional fields

        Returns:
            A new EnrichWithLMv3Request instance

        Example:
            request = EnrichWithLMv3RequestFactory.build()
            request = EnrichWithLMv3RequestFactory.build(
                dataset=BaseDatasetFactory.build(items=5)
            )
        """
        if dataset is None:
            dataset = BaseDatasetFactory.build()

        return EnrichWithLMv3Request(dataset=dataset, **kwargs)


class OCRRequestFactory(BaseFactory[OCRRequest]):
    """Factory for creating OCRRequest instances (engine-level)."""

    @classmethod
    def build(
        cls, input: Image.Image | None = None, mode: OCRMode = "text", **kwargs
    ) -> OCRRequest:
        """Build an OCRRequest instance.

        Args:
            input: PIL Image to process
            mode: OCR mode ("text" or "structured")
            **kwargs: Additional fields

        Returns:
            A new OCRRequest instance

        Example:
            request = OCRRequestFactory.build()
            request = OCRRequestFactory.build(
                input=Image.new("RGB", (800, 600)),
                mode="structured"
            )
        """
        if input is None:
            input = Image.new("RGB", (800, 600), color="white")

        return OCRRequest(input=input, mode=mode, **kwargs)


class LMv3RequestFactory(BaseFactory[LMv3Request]):
    """Factory for creating LMv3Request instances (engine-level)."""

    @classmethod
    def build(cls, input: Image.Image | None = None, **kwargs) -> LMv3Request:
        """Build an LMv3Request instance.

        Args:
            input: PIL Image to process (must be RGB/3-channel)
            **kwargs: Additional fields

        Returns:
            A new LMv3Request instance

        Example:
            request = LMv3RequestFactory.build()
            request = LMv3RequestFactory.build(input=Image.new("RGB", (1000, 800)))
        """
        if input is None:
            # LMv3Request requires 3-channel RGB image
            input = Image.new("RGB", (800, 600), color="white")

        return LMv3Request(input=input, **kwargs)


class CompletionRequestFactory(BaseFactory[CompletionRequest]):
    """Factory for creating CompletionRequest instances (engine-level)."""

    @classmethod
    def build(
        cls,
        input: Conversation | None = None,
        structured_output: type[BaseModel] | None = None,
        **kwargs,
    ) -> CompletionRequest:
        """Build a CompletionRequest instance.

        Args:
            input: Conversation history
            structured_output: Optional Pydantic model for structured output
            **kwargs: Additional fields

        Returns:
            A new CompletionRequest instance

        Example:
            request = CompletionRequestFactory.build()
            request = CompletionRequestFactory.build(
                input=ConversationFactory.build(message_count=3),
                structured_output=MySchema
            )
        """
        if input is None:
            input = ConversationFactory.build()

        return CompletionRequest(
            input=input, structured_output=structured_output, **kwargs
        )

    @classmethod
    def build_with_system_prompt(
        cls, system_prompt: str, structured_output: type[BaseModel] | None = None
    ) -> CompletionRequest:
        """Build a CompletionRequest with a system prompt.

        Args:
            system_prompt: The system prompt text
            structured_output: Optional Pydantic model for structured output

        Returns:
            A CompletionRequest with a system message

        Example:
            request = CompletionRequestFactory.build_with_system_prompt(
                "You are a helpful assistant"
            )
        """
        conversation = ConversationFactory.build_with_system_prompt(system_prompt)
        return cls.build(input=conversation, structured_output=structured_output)


class IngestPDFRequestFactory(BaseFactory[IngestPDFRequest]):
    """Factory for creating IngestPDFRequest instances.

    Example:
        # Build with PDF paths
        request = IngestPDFRequestFactory.build(pdf_paths=["doc1.pdf", "doc2.pdf"])

        # Build with source directory
        request = IngestPDFRequestFactory.build_with_source_dir("pdfs/")

        # Build with glob pattern
        request = IngestPDFRequestFactory.build_with_glob("pdfs/", "*.pdf")
    """

    @classmethod
    def build(
        cls,
        source_dir: str | None = None,
        pdf_paths: list[str] | None = None,
        glob_pattern: str = "*.pdf",
        **kwargs,
    ) -> IngestPDFRequest:
        """Build an IngestPDFRequest.

        Args:
            source_dir: Directory containing PDF files
            pdf_paths: List of PDF file paths
            glob_pattern: Pattern for matching PDF files
            **kwargs: Additional arguments for IngestPDFRequest

        Returns:
            IngestPDFRequest instance

        Example:
            request = IngestPDFRequestFactory.build(
                source_dir="pdfs/",
                glob_pattern="*.pdf"
            )
        """
        # Ensure at least one is provided to satisfy validation
        if source_dir is None and pdf_paths is None:
            pdf_paths = [f"test_document_{cls._counter}.pdf"]
            cls._counter += 1

        return IngestPDFRequest(
            source_dir=source_dir,
            pdf_paths=pdf_paths or [],
            glob_pattern=glob_pattern,
            **kwargs,
        )

    @classmethod
    def build_with_source_dir(
        cls, source_dir: str, glob_pattern: str = "*.pdf"
    ) -> IngestPDFRequest:
        """Build an IngestPDFRequest with a source directory.

        Args:
            source_dir: Directory containing PDF files
            glob_pattern: Pattern for matching PDF files

        Returns:
            IngestPDFRequest with source_dir configured

        Example:
            request = IngestPDFRequestFactory.build_with_source_dir("pdfs/")
        """
        return cls.build(source_dir=source_dir, glob_pattern=glob_pattern)

    @classmethod
    def build_with_pdf_paths(cls, pdf_paths: list[str]) -> IngestPDFRequest:
        """Build an IngestPDFRequest with specific PDF paths.

        Args:
            pdf_paths: List of PDF file paths

        Returns:
            IngestPDFRequest with pdf_paths configured

        Example:
            request = IngestPDFRequestFactory.build_with_pdf_paths(
                ["doc1.pdf", "doc2.pdf"]
            )
        """
        return cls.build(pdf_paths=pdf_paths)

    @classmethod
    def build_with_glob(cls, source_dir: str, glob_pattern: str) -> IngestPDFRequest:
        """Build an IngestPDFRequest with custom glob pattern.

        Args:
            source_dir: Directory containing PDF files
            glob_pattern: Custom pattern for matching files

        Returns:
            IngestPDFRequest with source_dir and glob_pattern configured

        Example:
            request = IngestPDFRequestFactory.build_with_glob(
                "documents/", "schematism_*.pdf"
            )
        """
        return cls.build(source_dir=source_dir, glob_pattern=glob_pattern)

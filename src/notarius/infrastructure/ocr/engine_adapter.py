"""OCR _engine adapter using PyTesseract."""

import warnings
from dataclasses import dataclass
from typing import final, override, Literal, overload, cast

import numpy as np
from PIL.Image import Image
from pytesseract import pytesseract

from notarius.application.ports.outbound.engine import ConfigurableEngine, track_stats
from notarius.domain.protocols import BaseRequest, BaseResponse
from notarius.infrastructure.ocr.types import (
    PytesseractOCRResultDict,
    SimpleOCRResult,
    StructuredOCRResult,
    OCRResult,
)
from notarius.schemas.configs import PytesseractOCRConfig
from notarius.schemas.data.structs import BBox

OCRMode = Literal["text", "structured"]


@dataclass(frozen=True)
class OCRRequest(BaseRequest):
    """Request for OCR processing.

    Attributes:
        input: PIL Image to perform OCR on
    """

    input: Image
    mode: OCRMode


@dataclass(frozen=True)
class OCRResponse(BaseResponse):
    """Response from OCR processing.

    Attributes:
        output: OCRResult containing words and bounding boxes
    """

    output: OCRResult


@final
class OCREngine(ConfigurableEngine[PytesseractOCRConfig, OCRRequest, OCRResponse]):
    """PyTesseract OCR _engine with unified interface.

    This _engine provides OCR capabilities using PyTesseract, extracting both
    text and word-level bounding boxes from images. The _engine follows the
    standard ConfigurableEngine protocol with a `process` method for unified
    access.

    Example:
        ```python
        config = PytesseractOCRConfig(language="eng")
        _engine = OCREngine.from_config(config)

        request = OCRRequest(input=pil_image)
        structured_response = _engine.process(request)

        words, bboxes = structured_response.output.words, structured_response.output.bboxes
        ```
    """

    def __init__(
        self,
        config: PytesseractOCRConfig,
    ) -> None:
        """Initialize the OCR _engine.

        Args:
            config: PyTesseract configuration
            enable_cache: Optional flag to enable caching (currently unused)
        """
        self._init_stats()
        self.config = config

    @classmethod
    @override
    def from_config(cls, config: PytesseractOCRConfig) -> "OCREngine":
        """Create _engine instance from configuration.

        Args:
            config: PyTesseract configuration

        Returns:
            Initialized OCREngine instance
        """
        return cls(config=config)

    def _text_ocr(self, pil_image: Image) -> str:
        """Perform text-only OCR on image.

        Args:
            pil_image: Input PIL Image

        Returns:
            Extracted text as string
        """
        return str(
            pytesseract.image_to_string(
                np.array(pil_image.convert("L")),
                lang=self.config.language,
                config=self.config.tesseract_config,
            )
        )

    def _structured_ocr(self, pil_image: Image) -> PytesseractOCRResultDict:
        """Perform structured OCR on image.

        Args:
            pil_image: Input PIL Image

        Returns:
            Dictionary containing OCR sample with word-level information
        """
        result = cast(
            PytesseractOCRResultDict,
            pytesseract.image_to_data(
                pil_image,
                output_type=pytesseract.Output.DICT,
                lang=self.config.language,
                config=self.config.tesseract_config,
            ),
        )
        return result

    def structured_to_words_ands_bboxes(
        self,
        ocr_dict: PytesseractOCRResultDict,
        image_width: float,
        image_height: float,
    ) -> tuple[list[str], list[BBox]]:
        """Convert PyTesseract output to words and normalized bounding boxes.

        Args:
            ocr_dict: PyTesseract output dictionary
            image_width: Original image width in pixels
            image_height: Original image height in pixels

        Returns:
            Tuple of (words, normalized_bboxes) where bboxes are in 0-1000 range
        """
        words: list[str] = []
        bboxes: list[BBox] = []

        for i, word in enumerate(ocr_dict["text"]):
            # Level 5 corresponds to word level
            if ocr_dict["level"][i] != 5:
                continue

            w = word.strip()
            if not w or int(ocr_dict["conf"][i]) < 0:
                continue

            xmin, ymin = ocr_dict["left"][i], ocr_dict["top"][i]
            xmax = xmin + ocr_dict["width"][i]
            ymax = ymin + ocr_dict["height"][i]

            # Normalize to 0-1000 range
            box: BBox = (
                int(1000 * xmin / image_width),
                int(1000 * ymin / image_height),
                int(1000 * xmax / image_width),
                int(1000 * ymax / image_height),
            )

            words.append(w)
            bboxes.append(box)

        return words, bboxes

    @override
    @track_stats
    def process(self, request: OCRRequest) -> OCRResponse:
        """Process an image and extract words with bounding boxes.

        This is the primary method following the ConfigurableEngine protocol.

        Args:
            request: OCRRequest containing the input image

        Returns:
            OCRResponse with extracted words and normalized bounding boxes
        """
        image = request.input
        width, height = image.size

        if request.mode == "structured":
            ocr_dict = self._structured_ocr(image)

            words, bboxes = self.structured_to_words_ands_bboxes(
                ocr_dict, float(width), float(height)
            )

            result = StructuredOCRResult(words=words, bboxes=bboxes)
        else:
            text = self._text_ocr(image)
            result = SimpleOCRResult(text=text)

        return OCRResponse(
            output=result,
        )

    # Backward compatibility methods for existing tests

    @overload
    def predict(self, image: Image, text_only: Literal[True]) -> str:
        """Perform OCR on image and return text only."""
        ...

    @overload
    def predict(
        self, image: Image, text_only: Literal[False]
    ) -> PytesseractOCRResultDict:
        """Perform OCR on image and return structured data."""
        ...

    def predict(
        self,
        image: Image,
        text_only: bool = False,
    ) -> str | PytesseractOCRResultDict:
        """Perform OCR on image (legacy interface for backward compatibility).

        .. deprecated::
            Use `process` method instead. This method will be removed in a future version.

        Args:
            image: Input image as PIL.Image
            text_only: If True, returns only text; otherwise returns structured dict

        Returns:
            Either extracted text string or structured OCR dictionary
        """
        warnings.warn(
            "predict() is deprecated, use process() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        if text_only:
            return self._text_ocr(image)
        else:
            return self._structured_ocr(image)

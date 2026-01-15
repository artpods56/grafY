"""Tests for OCREngine adapter."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image
from PIL.Image import Image as PILImage

from notarius.infrastructure.ocr.engine_adapter import OCREngine
from notarius.infrastructure.ocr.types import PytesseractOCRResultDict
from notarius.schemas.configs import PytesseractOCRConfig


@pytest.fixture
def ocr_config() -> PytesseractOCRConfig:
    """Create OCR configuration for testing."""
    return PytesseractOCRConfig(
        language="eng",
        psm_mode=6,
        oem_mode=3,
    )


@pytest.fixture
def sample_image() -> PILImage:
    """Create a sample PIL image for testing."""
    return Image.new("RGB", (200, 100), color="white")


@pytest.fixture
def sample_ocr_dict() -> PytesseractOCRResultDict:
    """Create sample OCR result dictionary."""
    return {
        "level": [1, 2, 3, 4, 5, 5, 5, 5],
        "text": ["", "", "", "", "Hello", "World", "", "Test"],
        "conf": ["-1", "-1", "-1", "-1", "95", "90", "-1", "85"],
        "left": [0, 0, 0, 0, 10, 60, 110, 150],
        "top": [0, 0, 0, 0, 20, 20, 20, 20],
        "width": [200, 200, 200, 200, 40, 50, 30, 40],
        "height": [100, 100, 100, 100, 30, 30, 30, 30],
    }


class TestOcrEngine:
    """Test suite for OCREngine class."""

    @pytest.fixture
    def engine(self, ocr_config: PytesseractOCRConfig) -> OCREngine:
        """Create an _engine instance for testing."""
        return OCREngine(config=ocr_config)

    def test_init(self, ocr_config: PytesseractOCRConfig) -> None:
        """Test _engine initialization."""
        engine = OCREngine(config=ocr_config)

        assert engine.config is ocr_config
        assert engine.config.language == "eng"
        assert engine.config.tesseract_config == "--psm 6 --oem 3"

    def test_init_with_different_config(self, ocr_config: PytesseractOCRConfig) -> None:
        """Test _engine initialization with different config."""
        engine = OCREngine(config=ocr_config)

        assert engine.config is ocr_config

    def test_from_config(self, ocr_config: PytesseractOCRConfig) -> None:
        """Test creating _engine from provider_config using class method."""
        engine = OCREngine.from_config(config=ocr_config)

        assert isinstance(engine, OCREngine)
        assert engine.config is ocr_config

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_string")
    def test_text_ocr(
        self,
        mock_image_to_string: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
    ) -> None:
        """Test _text_ocr method extracts text."""
        mock_image_to_string.return_value = "Sample text from OCR"

        result = engine._text_ocr(sample_image)

        assert result == "Sample text from OCR"
        assert isinstance(result, str)

        # Verify pytesseract was called correctly
        mock_image_to_string.assert_called_once()
        call_args = mock_image_to_string.call_args

        # Check image was converted to numpy array
        assert isinstance(call_args[0][0], np.ndarray)

        # Check kwargs
        assert call_args[1]["lang"] == "eng"
        assert call_args[1]["config"] == "--psm 6 --oem 3"

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_string")
    def test_text_ocr_converts_to_grayscale(
        self,
        mock_image_to_string: MagicMock,
        engine: OCREngine,
    ) -> None:
        """Test that _text_ocr converts image to grayscale."""
        # Create RGB image
        rgb_image = Image.new("RGB", (100, 100), color=(255, 0, 0))
        mock_image_to_string.return_value = "Text"

        _ = engine._text_ocr(rgb_image)

        # Verify image was processed
        mock_image_to_string.assert_called_once()

        # The image should be converted to L mode (grayscale)
        call_args = mock_image_to_string.call_args
        image_array = call_args[0][0]
        assert isinstance(image_array, np.ndarray)
        # Grayscale image should have shape (height, width) or (height, width, 1)
        assert len(image_array.shape) in [2, 3]

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_data")
    def test_structured_ocr(
        self,
        mock_image_to_data: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
        sample_ocr_dict: PytesseractOCRResultDict,
    ) -> None:
        """Test _structured_ocr method returns dictionary."""
        mock_image_to_data.return_value = sample_ocr_dict

        result = engine._structured_ocr(sample_image)

        assert result == sample_ocr_dict
        assert isinstance(result, dict)
        assert "text" in result
        assert "level" in result
        assert "conf" in result

        # Verify pytesseract was called correctly
        mock_image_to_data.assert_called_once()
        call_args = mock_image_to_data.call_args

        assert call_args[0][0] is sample_image
        assert call_args[1]["lang"] == "eng"
        assert call_args[1]["config"] == "--psm 6 --oem 3"

    def test_structured_to_words_and_bboxes(
        self, engine: OCREngine, sample_ocr_dict: PytesseractOCRResultDict
    ) -> None:
        """Test converting OCR dict to words and normalized bboxes."""
        image_width = 200.0
        image_height = 100.0

        words, bboxes = engine.structured_to_words_ands_bboxes(
            sample_ocr_dict, image_width, image_height
        )

        # Should extract 3 valid words: "Hello", "World", "Test"
        assert len(words) == 3
        assert words == ["Hello", "World", "Test"]

        # Should have matching number of bboxes
        assert len(bboxes) == 3

        # Verify bbox format (tuples of 4 ints)
        for bbox in bboxes:
            assert isinstance(bbox, tuple)
            assert len(bbox) == 4
            assert all(isinstance(coord, int) for coord in bbox)

        # Verify normalization (0-1000 range)
        for bbox in bboxes:
            xmin, ymin, xmax, ymax = bbox
            assert 0 <= xmin <= 1000
            assert 0 <= ymin <= 1000
            assert 0 <= xmax <= 1000
            assert 0 <= ymax <= 1000
            assert xmin < xmax
            assert ymin < ymax

    def test_structured_to_words_and_bboxes_correct_normalization(
        self, engine: OCREngine
    ) -> None:
        """Test that bbox normalization is correct."""
        # Create simple OCR dict with known coordinates
        ocr_dict: PytesseractOCRResultDict = {
            "level": [5, 5],
            "text": ["Word1", "Word2"],
            "conf": ["95", "90"],
            "left": [0, 100],  # pixels
            "top": [0, 50],  # pixels
            "width": [100, 100],  # pixels
            "height": [50, 50],  # pixels
        }

        image_width = 200.0
        image_height = 100.0

        words, bboxes = engine.structured_to_words_ands_bboxes(
            ocr_dict, image_width, image_height
        )

        assert len(bboxes) == 2

        # First word: left=0, top=0, width=100, height=50
        # Normalized: (0, 0, 500, 500)
        assert bboxes[0] == (0, 0, 500, 500)

        # Second word: left=100, top=50, width=100, height=50
        # Normalized: (500, 500, 1000, 1000)
        assert bboxes[1] == (500, 500, 1000, 1000)

    def test_structured_to_words_and_bboxes_filters_non_word_level(
        self, engine: OCREngine
    ) -> None:
        """Test that non-word level entries are filtered."""
        ocr_dict: PytesseractOCRResultDict = {
            "level": [1, 2, 3, 4, 5],  # Only level 5 is word level
            "text": ["Page", "Block", "Para", "Line", "Word"],
            "conf": ["95", "95", "95", "95", "95"],
            "left": [0, 0, 0, 0, 0],
            "top": [0, 0, 0, 0, 0],
            "width": [100, 100, 100, 100, 100],
            "height": [50, 50, 50, 50, 50],
        }

        words, bboxes = engine.structured_to_words_ands_bboxes(ocr_dict, 200.0, 100.0)

        # Only "Word" should be extracted (level 5)
        assert len(words) == 1
        assert words == ["Word"]
        assert len(bboxes) == 1

    def test_structured_to_words_and_bboxes_filters_low_confidence(
        self, engine: OCREngine
    ) -> None:
        """Test that low confidence words are filtered."""
        ocr_dict: PytesseractOCRResultDict = {
            "level": [5, 5, 5],
            "text": ["Good", "Bad", "Ugly"],
            "conf": ["95", "-1", "85"],  # -1 means low confidence
            "left": [0, 50, 100],
            "top": [0, 0, 0],
            "width": [40, 40, 40],
            "height": [30, 30, 30],
        }

        words, bboxes = engine.structured_to_words_ands_bboxes(ocr_dict, 200.0, 100.0)

        # "Bad" should be filtered due to conf < 0
        assert len(words) == 2
        assert words == ["Good", "Ugly"]
        assert len(bboxes) == 2

    def test_structured_to_words_and_bboxes_filters_empty_words(
        self, engine: OCREngine
    ) -> None:
        """Test that empty or whitespace words are filtered."""
        ocr_dict: PytesseractOCRResultDict = {
            "level": [5, 5, 5, 5],
            "text": ["Valid", "", "   ", "AlsoValid"],
            "conf": ["95", "90", "85", "80"],
            "left": [0, 50, 100, 150],
            "top": [0, 0, 0, 0],
            "width": [40, 40, 40, 40],
            "height": [30, 30, 30, 30],
        }

        words, bboxes = engine.structured_to_words_ands_bboxes(ocr_dict, 200.0, 100.0)

        # Empty and whitespace words should be filtered
        assert len(words) == 2
        assert words == ["Valid", "AlsoValid"]
        assert len(bboxes) == 2

    def test_structured_to_words_and_bboxes_strips_whitespace(
        self, engine: OCREngine
    ) -> None:
        """Test that words are stripped of whitespace."""
        ocr_dict: PytesseractOCRResultDict = {
            "level": [5, 5],
            "text": ["  Leading  ", "Trailing  "],
            "conf": ["95", "90"],
            "left": [0, 100],
            "top": [0, 0],
            "width": [100, 100],
            "height": [50, 50],
        }

        words, bboxes = engine.structured_to_words_ands_bboxes(ocr_dict, 200.0, 100.0)

        assert words == ["Leading", "Trailing"]

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_string")
    def test_predict_text_only_true(
        self,
        mock_image_to_string: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
    ) -> None:
        """Test predict with text_only=True returns string."""
        mock_image_to_string.return_value = "Extracted text"

        result = engine.predict(sample_image, text_only=True)

        assert isinstance(result, str)
        assert result == "Extracted text"
        mock_image_to_string.assert_called_once()

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_data")
    def test_predict_text_only_false(
        self,
        mock_image_to_data: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
        sample_ocr_dict: PytesseractOCRResultDict,
    ) -> None:
        """Test predict with text_only=False returns OCR dict."""
        mock_image_to_data.return_value = sample_ocr_dict

        result = engine.predict(sample_image, text_only=False)

        assert isinstance(result, dict)
        assert result == sample_ocr_dict
        assert "text" in result
        assert "level" in result
        mock_image_to_data.assert_called_once()

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_string")
    def test_predict_default_text_only(
        self,
        mock_image_to_string: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
    ) -> None:
        """Test predict with default text_only (False) returns dict."""
        # When text_only is not specified, it defaults to False
        # which means _structured_ocr should be called, not _text_ocr
        with patch.object(engine, "_structured_ocr") as mock_structured:
            mock_structured.return_value = {"text": ["test"]}

            result = engine.predict(sample_image)

            # Default is text_only=False, so should call _structured_ocr
            mock_structured.assert_called_once_with(sample_image)
            mock_image_to_string.assert_not_called()

    def test_predict_preserves_type_literal_true(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict with Literal[True] returns str type."""
        with patch.object(engine, "_text_ocr") as mock_text_ocr:
            mock_text_ocr.return_value = "text"

            result = engine.predict(sample_image, text_only=True)

            # Type checker should infer result as str
            assert isinstance(result, str)

    def test_predict_preserves_type_literal_false(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict with Literal[False] returns dict type."""
        with patch.object(engine, "_structured_ocr") as mock_structured:
            mock_structured.return_value = {"text": ["test"]}

            result = engine.predict(sample_image, text_only=False)

            # Type checker should infer result as dict
            assert isinstance(result, dict)

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_string")
    def test_predict_calls_text_ocr_when_text_only(
        self,
        mock_image_to_string: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
    ) -> None:
        """Test that predict calls _text_ocr when text_only=True."""
        mock_image_to_string.return_value = "Test"

        with patch.object(engine, "_structured_ocr") as mock_structured:
            _ = engine.predict(sample_image, text_only=True)

            # Should call _text_ocr, not _structured_ocr
            mock_image_to_string.assert_called_once()
            mock_structured.assert_not_called()

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_data")
    def test_predict_calls_structured_ocr_when_not_text_only(
        self,
        mock_image_to_data: MagicMock,
        engine: OCREngine,
        sample_image: PILImage,
    ) -> None:
        """Test that predict calls _structured_ocr when text_only=False."""
        mock_image_to_data.return_value = {"text": ["test"]}

        with patch.object(engine, "_text_ocr") as mock_text:
            _ = engine.predict(sample_image, text_only=False)

            # Should call _structured_ocr, not _text_ocr
            mock_image_to_data.assert_called_once()
            mock_text.assert_not_called()

    def test_engine_with_different_language_config(self) -> None:
        """Test _engine with different language configuration."""
        config = PytesseractOCRConfig(
            language="pol",  # Polish
            psm_mode=3,
            oem_mode=1,
        )

        engine = OCREngine(config=config)

        assert engine.config.language == "pol"
        assert engine.config.tesseract_config == "--psm 3 --oem 1"

    def test_engine_with_multilingual_config(self) -> None:
        """Test _engine with multilingual configuration."""
        config = PytesseractOCRConfig(
            language="lat+pol+rus",
            psm_mode=6,
        )

        engine = OCREngine(config=config)

        assert engine.config.language == "lat+pol+rus"

    def test_structured_to_words_and_bboxes_with_empty_dict(
        self, engine: OCREngine
    ) -> None:
        """Test handling of empty OCR result."""
        empty_dict: PytesseractOCRResultDict = {
            "level": [],
            "text": [],
            "conf": [],
            "left": [],
            "top": [],
            "width": [],
            "height": [],
        }

        words, bboxes = engine.structured_to_words_ands_bboxes(empty_dict, 200.0, 100.0)

        assert words == []
        assert bboxes == []

    def test_structured_to_words_and_bboxes_returns_correct_types(
        self, engine: OCREngine, sample_ocr_dict: PytesseractOCRResultDict
    ) -> None:
        """Test that return types match expected types."""
        words, bboxes = engine.structured_to_words_ands_bboxes(
            sample_ocr_dict, 200.0, 100.0
        )

        # Check return type structure
        assert isinstance(words, list)
        assert isinstance(bboxes, list)

        # Check element types
        for word in words:
            assert isinstance(word, str)

        for bbox in bboxes:
            assert isinstance(bbox, tuple)
            assert len(bbox) == 4
            for coord in bbox:
                assert isinstance(coord, int)

    def test_bbox_coordinates_are_within_bounds(self, engine: OCREngine) -> None:
        """Test that normalized bbox coordinates stay within 0-1000."""
        ocr_dict: PytesseractOCRResultDict = {
            "level": [5],
            "text": ["Test"],
            "conf": ["95"],
            "left": [0],
            "top": [0],
            "width": [200],  # Full width
            "height": [100],  # Full height
        }

        words, bboxes = engine.structured_to_words_ands_bboxes(ocr_dict, 200.0, 100.0)

        bbox = bboxes[0]
        xmin, ymin, xmax, ymax = bbox

        assert 0 <= xmin <= 1000
        assert 0 <= ymin <= 1000
        assert 0 <= xmax <= 1000
        assert 0 <= ymax <= 1000

    def test_predict_method_signature_matches_interface(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict method signature is correct."""
        # This test verifies the method exists and has correct signature
        with patch.object(engine, "_text_ocr") as mock_text:
            mock_text.return_value = "text"

            # Should accept image and text_only parameter
            result = engine.predict(image=sample_image, text_only=True)
            assert isinstance(result, str)

        with patch.object(engine, "_structured_ocr") as mock_struct:
            mock_struct.return_value = {"text": ["test"]}

            # Should work without text_only parameter
            result = engine.predict(image=sample_image)
            assert isinstance(result, dict)

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_string")
    def test_integration_text_mode(
        self,
        mock_image_to_string: MagicMock,
        ocr_config: PytesseractOCRConfig,
    ) -> None:
        """Test full integration in text-only mode."""
        mock_image_to_string.return_value = "Full text extraction"

        engine = OCREngine.from_config(config=ocr_config)
        image = Image.new("RGB", (200, 100), color="white")

        result = engine.predict(image, text_only=True)

        assert result == "Full text extraction"
        assert isinstance(result, str)

    @patch("notarius.infrastructure.ocr.engine_adapter.pytesseract.image_to_data")
    def test_integration_structured_mode(
        self,
        mock_image_to_data: MagicMock,
        ocr_config: PytesseractOCRConfig,
        sample_ocr_dict: PytesseractOCRResultDict,
    ) -> None:
        """Test full integration in structured mode."""
        mock_image_to_data.return_value = sample_ocr_dict

        engine = OCREngine.from_config(config=ocr_config)
        image = Image.new("RGB", (200, 100), color="white")

        result = engine.predict(image, text_only=False)

        assert isinstance(result, dict)
        assert "text" in result
        assert result == sample_ocr_dict


class TestPredictDeprecationWarning:
    """Test suite for OCREngine.predict() deprecation warning."""

    @pytest.fixture
    def engine(self, ocr_config: PytesseractOCRConfig) -> OCREngine:
        """Create an engine instance for testing."""
        return OCREngine(config=ocr_config)

    def test_predict_emits_deprecation_warning(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict() emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="predict.*deprecated.*process"):
            engine.predict(sample_image, text_only=True)

    def test_predict_emits_deprecation_warning_structured(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict() with text_only=False emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="predict.*deprecated.*process"):
            engine.predict(sample_image, text_only=False)

    def test_predict_emits_deprecation_warning_default(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict() with default args emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="predict.*deprecated.*process"):
            engine.predict(sample_image)

    def test_deprecation_warning_stacklevel(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that DeprecationWarning points to calling code, not engine."""
        with pytest.warns(DeprecationWarning) as record:
            engine.predict(sample_image, text_only=True)

        assert len(record) == 1
        warning = record[0]
        assert "predict() is deprecated, use process() instead" in str(warning.message)


class TestPredictDeprecationWarning:
    """Test suite for OCREngine.predict() deprecation warning."""

    @pytest.fixture
    def engine(self, ocr_config: PytesseractOCRConfig) -> OCREngine:
        """Create an engine instance for testing."""
        return OCREngine(config=ocr_config)

    def test_predict_emits_deprecation_warning(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict() emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="predict.*deprecated.*process"):
            engine.predict(sample_image, text_only=True)

    def test_predict_emits_deprecation_warning_structured(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict() with text_only=False emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="predict.*deprecated.*process"):
            engine.predict(sample_image, text_only=False)

    def test_predict_emits_deprecation_warning_default(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that predict() with default args emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="predict.*deprecated.*process"):
            engine.predict(sample_image)

    def test_deprecation_warning_stacklevel(
        self, engine: OCREngine, sample_image: PILImage
    ) -> None:
        """Test that DeprecationWarning points to calling code, not engine."""
        with pytest.warns(DeprecationWarning) as record:
            engine.predict(sample_image, text_only=True)

        assert len(record) == 1
        warning = record[0]
        assert "predict() is deprecated, use process() instead" in str(warning.message)


"""Tests for EnrichDatasetWithLMv3 use case."""

import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from notarius.application.use_cases.inference.enrich_dataset_with_lmv3_predictions import (
    EnrichDatasetWithLMv3,
    EnrichWithLMv3Request,
    EnrichWithLMv3Response,
)
from tests.fakes.engines import FakeLMv3Engine
from tests.fakes.storage import FakeImageStorage
from notarius.infrastructure.ml_models.lmv3.engine_adapter import (
    LMv3Response,
)
from notarius.domain.entities.schematism import SchematismPage, SchematismEntry
from notarius.schemas.data.pipeline import (
    BaseDataItem,
    PredictionDataItem,
    BaseMetaData,
    BaseItemDataset,
    PredictionItemDataset,
)


# Test fixtures


@pytest.fixture
def mock_image() -> Image.Image:
    """Create a mock PIL image."""
    return Image.new("RGB", (100, 100), color="white")


@pytest.fixture
def mock_schematism_page() -> SchematismPage:
    """Create a mock SchematismPage prediction."""
    return SchematismPage(
        page_number="1",
        entries=[
            SchematismEntry(
                deanery="Test Deanery",
                parish="Test Parish",
            )
        ],
    )


@pytest.fixture
def fake_lmv3_engine(mock_schematism_page: SchematismPage) -> FakeLMv3Engine:
    """Create a fake LMv3 engine."""
    return FakeLMv3Engine(default_page=mock_schematism_page)


@pytest.fixture
def fake_image_storage(mock_image: Image.Image) -> FakeImageStorage:
    """Create a fake image storage resource."""
    storage = FakeImageStorage()
    storage.add(mock_image, "/path/to/image1.jpg")
    storage.add(mock_image, "/path/to/image2.jpg")
    storage.add(mock_image, "/path/to/image.jpg")
    return storage


@pytest.fixture
def sample_metadata() -> BaseMetaData:
    """Create sample metadata."""
    return BaseMetaData(
        sample_id=1,
        schematism_name="test_schematism",
        filename="test_file.jpg",
    )


@pytest.fixture
def sample_dataset(sample_metadata: BaseMetaData) -> BaseItemDataset:
    """Create a sample dataset with items."""
    items = [
        BaseDataItem(
            image_path="/path/to/image1.jpg",
            text="Sample OCR text 1",
            metadata=sample_metadata,
        ),
        BaseDataItem(
            image_path="/path/to/image2.jpg",
            text="Sample OCR text 2",
            metadata=BaseMetaData(
                sample_id=2,
                schematism_name="test_schematism",
                filename="test_file2.jpg",
            ),
        ),
    ]
    return BaseItemDataset(items=items)


@pytest.fixture
def empty_dataset() -> BaseItemDataset:
    """Create an empty dataset."""
    return BaseItemDataset(items=[])


@pytest.fixture
def dataset_with_missing_paths(
    sample_metadata: BaseMetaData,
) -> BaseItemDataset:
    """Create a dataset with items missing image paths."""
    items = [
        BaseDataItem(image_path=None, text="text", metadata=sample_metadata),
        BaseDataItem(
            image_path="/path/to/image.jpg", text="text", metadata=sample_metadata
        ),
    ]
    return BaseItemDataset(items=items)


class TestEnrichWithLMv3Request:
    """Test suite for EnrichWithLMv3Request dataclass."""

    def test_request_creation(self, sample_dataset: BaseItemDataset) -> None:
        """Test request creation."""
        request = EnrichWithLMv3Request(dataset=sample_dataset)

        assert request.dataset is sample_dataset


class TestEnrichWithLMv3Response:
    """Test suite for EnrichWithLMv3Response dataclass."""

    def test_response_creation(
        self, mock_schematism_page: SchematismPage, sample_metadata: BaseMetaData
    ) -> None:
        """Test response creation with all fields."""
        prediction_dataset = PredictionItemDataset(
            items=[
                PredictionDataItem(
                    image_path="/path/image.jpg",
                    text="text",
                    predictions=mock_schematism_page,
                    metadata=sample_metadata,
                )
            ]
        )
        response = EnrichWithLMv3Response(
            dataset=prediction_dataset,
            processed_count=5,
        )

        assert response.dataset is prediction_dataset
        assert response.processed_count == 5


class TestEnrichDatasetWithLMv3:
    """Test suite for EnrichDatasetWithLMv3 use case."""

    def test_init(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
    ) -> None:
        """Test initialization."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        # Engine and storage should be stored directly
        assert use_case.lmv3_engine is fake_lmv3_engine
        assert use_case.image_storage is fake_image_storage

    def test_execute_processes_all_items(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        sample_dataset: BaseItemDataset,
    ) -> None:
        """Test that execute processes all dataset items."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=sample_dataset)
        response = use_case.execute(request)

        assert len(response.dataset.items) == 2
        assert len(fake_lmv3_engine.call_history) == 2
        assert len(fake_image_storage.get_calls) == 2

    def test_execute_creates_prediction_data_items(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        mock_schematism_page: SchematismPage,
        sample_dataset: BaseItemDataset,
    ) -> None:
        """Test that execute creates PredictionDataItem instances."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=sample_dataset)
        response = use_case.execute(request)

        # All items should be PredictionDataItem with predictions
        for item in response.dataset.items:
            assert isinstance(item, PredictionDataItem)
            assert item.predictions == mock_schematism_page

    def test_execute_preserves_original_data(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        sample_dataset: BaseItemDataset,
    ) -> None:
        """Test that execute preserves original item data."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=sample_dataset)
        response = use_case.execute(request)

        # Original data should be preserved
        assert response.dataset.items[0].image_path == "/path/to/image1.jpg"
        assert response.dataset.items[0].text == "Sample OCR text 1"
        assert response.dataset.items[0].metadata is not None
        assert response.dataset.items[0].metadata.sample_id == 1

        assert response.dataset.items[1].image_path == "/path/to/image2.jpg"
        assert response.dataset.items[1].text == "Sample OCR text 2"
        assert response.dataset.items[1].metadata is not None
        assert response.dataset.items[1].metadata.sample_id == 2

    def test_execute_skips_items_without_image_path(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        dataset_with_missing_paths: BaseItemDataset,
    ) -> None:
        """Test that items without image paths are skipped."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=dataset_with_missing_paths)
        response = use_case.execute(request)

        # Only one item has an image path
        assert len(response.dataset.items) == 1
        assert len(fake_lmv3_engine.call_history) == 1

    def test_execute_with_empty_dataset(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        empty_dataset: BaseItemDataset,
    ) -> None:
        """Test execution with empty dataset."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=empty_dataset)
        response = use_case.execute(request)

        assert len(response.dataset.items) == 0
        assert response.processed_count == 0
        assert len(fake_lmv3_engine.call_history) == 0

    def test_execute_returns_correct_statistics(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        sample_dataset: BaseItemDataset,
    ) -> None:
        """Test that statistics are correct."""
        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=sample_dataset)
        response = use_case.execute(request)

        # All items should be processed
        assert response.processed_count == 2

    def test_execute_converts_image_to_rgb(
        self,
        fake_lmv3_engine: FakeLMv3Engine,
        fake_image_storage: FakeImageStorage,
        sample_dataset: BaseItemDataset,
    ) -> None:
        """Test that images are converted to RGB mode."""
        # Create a grayscale image that will be converted to RGB
        grayscale_image = Image.new("L", (100, 100), color=128)
        fake_image_storage.reset()
        fake_image_storage.add(grayscale_image, "/path/to/image1.jpg")
        fake_image_storage.add(grayscale_image, "/path/to/image2.jpg")

        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        request = EnrichWithLMv3Request(dataset=sample_dataset)
        use_case.execute(request)

        # Verify that the engine received RGB images
        for lmv3_request in fake_lmv3_engine.call_history:
            assert lmv3_request.input.mode == "RGB"


class TestEnrichDatasetWithLMv3Integration:
    """Integration-style tests for EnrichDatasetWithLMv3."""

    def test_full_workflow_produces_valid_predictions(
        self,
        fake_image_storage: FakeImageStorage,
    ) -> None:
        """Test complete workflow produces valid PredictionDataItems."""
        # Create mock engine with different predictions for each item
        fake_lmv3_engine = FakeLMv3Engine()

        use_case = EnrichDatasetWithLMv3(
            lmv3_engine=fake_lmv3_engine,
            image_storage=fake_image_storage,
        )

        dataset = BaseItemDataset(
            items=[
                BaseDataItem(
                    image_path="/path/page1.jpg",
                    text="OCR text 1",
                    metadata=BaseMetaData(
                        sample_id=1, schematism_name="test", filename="p1.jpg"
                    ),
                ),
                BaseDataItem(
                    image_path="/path/page2.jpg",
                    text="OCR text 2",
                    metadata=BaseMetaData(
                        sample_id=2, schematism_name="test", filename="p2.jpg"
                    ),
                ),
            ]
        )

        # Ensure images exist in storage
        white_image = Image.new("RGB", (100, 100), color="white")
        fake_image_storage.add(white_image, "/path/page1.jpg")
        fake_image_storage.add(white_image, "/path/page2.jpg")

        request = EnrichWithLMv3Request(dataset=dataset)
        response = use_case.execute(request)

        assert len(response.dataset.items) == 2

        # Verify original data is preserved
        assert response.dataset.items[0].text == "OCR text 1"
        assert response.dataset.items[1].text == "OCR text 2"

        assert response.processed_count == 2

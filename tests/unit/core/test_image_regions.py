import pytest
from pydantic import ValidationError

from grafy_core.artifact_contracts import ImagePage, ImageRegion, ImageRegionSet


def test_region_set_declares_pages_and_looks_up_by_index() -> None:
    first = ImagePage(index=3, width=200, height=100)
    second = ImagePage(index=0, width=50, height=80)
    regions = ImageRegionSet(
        pages=[first, second],
        regions=[ImageRegion(page=3, x0=1, y0=2, x1=3, y1=4, kind="image")],
    )
    assert regions.page(3) == first
    assert regions.page(0) == second
    assert regions.page(1) is None
    assert ImageRegion(x0=0, y0=0, x1=1, y1=1, kind="text").page == 0
    assert ImageRegionSet.model_validate_json(regions.model_dump_json()) == regions


def test_region_set_rejects_duplicate_page_indexes() -> None:
    with pytest.raises(ValidationError, match="region set page indexes must be unique"):
        _ = ImageRegionSet(
            pages=[
                ImagePage(index=0, width=10, height=20),
                ImagePage(index=0, width=30, height=40),
            ],
            regions=[],
        )


def test_region_set_rejects_undeclared_region_page() -> None:
    with pytest.raises(
        ValidationError, match="region page 2 is not declared in the region set"
    ):
        _ = ImageRegionSet(
            pages=[ImagePage(index=0, width=10, height=20)],
            regions=[ImageRegion(page=2, x0=0, y0=0, x1=1, y1=1, kind="text")],
        )


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [{"index": -1, "width": 10, "height": 20}],
        [{"index": 0, "width": 0, "height": 20}],
        [{"index": "0", "width": 10, "height": 20}],
    ],
)
def test_region_set_requires_nonempty_valid_pages(
    pages: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        _ = ImageRegionSet.model_validate({"pages": pages, "regions": []})

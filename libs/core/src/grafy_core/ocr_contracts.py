"""OCR reader service contract and the value it returns.

App-owned. Provider plugins implement ``OcrReader``; the workbench OCR node is
the only consumer. ``features`` is a class attribute so the catalog can report
what a provider produces without running it.
"""

from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from grafy_core.artifact_contracts import ImageRegionSet, MarkdownValue
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.node_context import UserFacingNodeError
from grafy_core.service_contracts import service_contract
from grafy_core.table_contracts import Table


class OcrFeature(StrEnum):
    BLOCKS = "blocks"
    REGIONS = "regions"


class OcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: MarkdownValue
    blocks: Table | None = None
    regions: ImageRegionSet | None = None


@service_contract("ocr.reader", version=1, title="OCR service")
@runtime_checkable
class OcrReader(Protocol):
    features: ClassVar[frozenset[OcrFeature]]
    # Same string as the provider node's title. Recorded on unsupported outputs.
    title: ClassVar[str]

    async def read(self, document: RasterImage | PdfFile) -> OcrResult: ...


_FEATURE_PORTS: tuple[tuple[OcrFeature, str], ...] = (
    (OcrFeature.BLOCKS, "blocks"),
    (OcrFeature.REGIONS, "regions"),
)


def check_ocr_result(reader: OcrReader, result: OcrResult) -> dict[str, str]:
    """Refuse a feature/result mismatch; return ports the provider does not produce.

    A declared feature with a ``None`` value, or an undeclared feature with a
    value, fails the computation and names the provider. Undeclared features
    that stay ``None`` become ``unsupported_outputs`` entries keyed by port name.
    """

    title = type(reader).title
    features = type(reader).features
    unsupported: dict[str, str] = {}
    for feature, port in _FEATURE_PORTS:
        value = getattr(result, port)
        if feature in features:
            if value is None:
                raise UserFacingNodeError(
                    f"{title} declared {feature.value} but returned none"
                )
            continue
        if value is not None:
            raise UserFacingNodeError(
                f"{title} returned {feature.value} without declaring it"
            )
        unsupported[port] = title
    return unsupported


def reader_feature_values(cls: type[object]) -> tuple[str, ...]:
    """Sorted feature strings declared on a reader class, or empty."""

    raw = getattr(cls, "features", None)
    if not isinstance(raw, frozenset | set | tuple | list):
        return ()
    values: list[str] = []
    for item in raw:
        if isinstance(item, OcrFeature):
            values.append(item.value)
        else:
            values.append(str(item))
    return tuple(sorted(values))


__all__ = [
    "OcrFeature",
    "OcrReader",
    "OcrResult",
    "check_ocr_result",
    "reader_feature_values",
]

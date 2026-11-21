"""Pixel-space contracts for text localization and recognition."""

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Annotated, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from grafy_core.service_contracts import service_contract

type PixelCoordinate = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
type PixelPoint = tuple[PixelCoordinate, PixelCoordinate]
type PixelPolygon = Annotated[list[PixelPoint], Field(min_length=3)]


class TextRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    polygon: PixelPolygon
    text: str | None = None
    score: float | None = Field(default=None, allow_inf_nan=False)


@service_contract("ocr.text_detector", version=1, title="Text detector")
class TextDetector(Protocol):
    async def detect(
        self, png: bytes, *, width: int, height: int
    ) -> list[TextRegion]: ...


def detector_request_options(detector: TextDetector) -> dict[str, float]:
    """Tuning parameters a detector sends with every request, e.g. CRAFT thresholds.

    Detectors that accept them expose a ``request_options`` mapping; the scan
    mirrors it into the provider cache key so two configurations never share
    cached detections.
    """
    options = cast(
        "dict[str, object] | None", getattr(detector, "request_options", None)
    )
    if options is None:
        return {}
    cleaned: dict[str, float] = {}
    for key, value in options.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cleaned[key] = float(value)
    return cleaned


class TextReading(BaseModel):
    """A recognizer's raw transcription of a single crop."""

    model_config = ConfigDict(extra="forbid", strict=True)

    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    model: str = Field(min_length=1)


@service_contract("ocr.text_recognizer", version=1, title="Text recognizer")
class TextRecognizer(Protocol):
    async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
        """Return one reading per crop in input order."""
        ...


class TiffWindowReader(Protocol):
    async def __call__(
        self, *, col: int, row: int, width: int, height: int
    ) -> bytes: ...


_SHA256 = re.compile(r"[0-9a-f]{64}")

type PixelAffine = tuple[float, float, float, float, float, float]
"""GDAL/rasterio ``(a, b, c, d, e, f)``: ``x = a*col + b*row + c`` and
``y = d*col + e*row + f``, where ``(col, row)`` is a pixel corner of the page."""


@dataclass(frozen=True, slots=True)
class TiffPage:
    width: int
    height: int
    read: TiffWindowReader
    source_sha256: str
    page: int
    # Both are set for a georeferenced page and both are None otherwise.
    affine: PixelAffine | None = None
    crs: str | None = None

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.source_sha256) is None:
            raise ValueError(
                "TIFF page source_sha256 must be a 64-character lowercase hex digest"
            )
        if self.page < 0:
            raise ValueError("TIFF page index must not be negative")
        if (self.affine is None) != (self.crs is None):
            raise ValueError("TIFF page affine and CRS must be present together")


class TiffPageOpener(Protocol):
    async def __call__(
        self, workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage: ...

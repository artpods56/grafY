"""Pixel-based symbol classification for historical TIFF map labels."""

from math import log, log1p, radians, sin

from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from grafy_core.text_regions import PixelPolygon

CONTEXT_PIXELS = 16

# Standardized logistic model fitted on labeled CRAFT regions from eight
# windows of one historical sheet. The scaler is folded into these weights.
_WEIGHTS = (
    0.0572770377022,
    -0.214305663751,
    -0.440193187123,
    -1.02945729487,
    0.495796335894,
    -0.00505056629982,
    -0.00854434406729,
    -0.003783690143,
    -0.107773797212,
    -0.0726250675869,
    -0.0664336840413,
    0.0141450825934,
    -0.0089476334671,
    -0.0359112088736,
    1.03848090407,
    0.00642795638366,
    -0.000877614683397,
    -0.00762445111955,
    -0.0751335635216,
    -0.0820528619913,
    -0.0750084264246,
    0.0329441857324,
    -0.00103357404059,
    -0.0431132508843,
    1.69609275403,
    -0.000868458404565,
    -0.00246600833344,
    -0.00451912145279,
    -0.135096453691,
    -0.0823657044231,
    -0.0316252767651,
    0.0376556083993,
    0.0273061301061,
    -0.0209980165928,
    0.625750609489,
    1.18109092755,
    -1.53624860414,
    -10.0361599819,
    -1.09298918294,
    -2.9843435154,
    3.31189176813,
    -5.75138010929,
    4.92325424925,
)
_BIAS = 94.5396714792


def is_map_symbol(png: bytes, polygon: PixelPolygon, *, threshold: float) -> bool:
    """Classify a region using its unrotated pixels and surrounding map context."""
    pixels = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None or threshold == 1:
        return False
    points = np.rint(polygon).astype(np.int32)
    _, _, width, height = cv2.boundingRect(points)
    _, (side_a, side_b), angle = cv2.minAreaRect(points.astype(np.float32))
    if min(side_a, side_b) <= 0:
        return False
    short, long = sorted((side_a, side_b))
    if side_a < side_b:
        angle += 90
    mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [points], 1)
    inside = mask.astype(bool)
    if not inside.any():
        return False

    lab = cast(NDArray[np.uint8], cv2.cvtColor(pixels, cv2.COLOR_BGR2LAB))
    lightness = lab[:, :, 0].astype(np.float32)
    red_green = lab[:, :, 1]
    blue_yellow = lab[:, :, 2]
    ink = lightness < np.percentile(lightness[inside], 30)
    features = [
        log1p(short),
        log1p(long),
        log1p(long / max(short, 1)),
        abs(sin(radians(angle))),
        cv2.contourArea(points) / (width * height),
    ]
    for selection in (inside, inside & ink, ~inside & (lightness > 115)):
        for channel in (lightness, red_green, blue_yellow):
            values = channel[selection].astype(np.float64)
            if values.size:
                features.extend(
                    float(np.percentile(values, percentile))
                    for percentile in (20, 50, 80)
                )
            else:
                features.extend([128.0] * 3)
        features.append(
            float(np.mean(red_green[selection] < 123)) if selection.any() else 0.0
        )

    reduced = cast(NDArray[np.float32], cv2.resize(lightness, (36, 24)))
    dx = cast(NDArray[np.float32], cv2.Sobel(reduced, cv2.CV_32F, 1, 0))
    dy = cast(NDArray[np.float32], cv2.Sobel(reduced, cv2.CV_32F, 0, 1))
    histogram, _ = np.histogram(
        np.arctan2(dy, dx) % np.pi,
        bins=8,
        range=(0, np.pi),
        weights=np.hypot(dx, dy),
    )
    features.extend(
        float(value) / max(float(histogram.sum()), 1) for value in histogram
    )
    log_odds = _BIAS + sum(
        feature * weight for feature, weight in zip(features, _WEIGHTS, strict=True)
    )
    return log_odds >= log(threshold / (1 - threshold))

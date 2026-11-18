"""Read the pixels for one TIFF polygon and prepare a single OCR line."""

from io import BytesIO
from math import atan2, ceil, degrees, floor, hypot

from PIL import Image, ImageDraw, ImageFilter, ImageOps
from shapely import Polygon

from grafy_core.node_context import UserFacingNodeError
from grafy_core.text_regions import PixelPolygon, TiffPage

_MARGIN = 4
_NATIVE_PIXEL_LIMIT = 1_000_000


def _deskew_angle(points: PixelPolygon) -> float | None:
    envelope = Polygon(points).minimum_rotated_rectangle
    if not isinstance(envelope, Polygon) or envelope.is_empty:
        return None
    coordinates = list(envelope.exterior.coords)
    edges = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(coordinates, coordinates[1:])]
    dx, dy = max(edges, key=lambda edge: hypot(*edge))
    if dx < 0 or (dx == 0 and dy < 0):
        dx, dy = -dx, -dy
    return degrees(atan2(dy, dx))


async def read_label_crop(page: TiffPage, polygon: PixelPolygon) -> bytes | None:
    angle = _deskew_angle(polygon)
    if angle is None:
        return None
    xs, ys = zip(*polygon)
    left, top, right, bottom = (
        floor(min(xs)),
        floor(min(ys)),
        ceil(max(xs)),
        ceil(max(ys)),
    )
    if right > page.width or bottom > page.height:
        raise UserFacingNodeError("A text polygon extends outside its source TIFF page")
    col, row = max(0, left - _MARGIN), max(0, top - _MARGIN)
    width = min(page.width, right + _MARGIN) - col
    height = min(page.height, bottom + _MARGIN) - row
    if width * height > _NATIVE_PIXEL_LIMIT:
        col, row, width, height = left, top, right - left, bottom - top
    if width * height > _NATIVE_PIXEL_LIMIT:
        raise UserFacingNodeError("A label exceeds the native TIFF read limit")

    png = await page.read(col=col, row=row, width=width, height=height)
    with Image.open(BytesIO(png)) as source:
        rgba = source.convert("RGBA")
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).polygon([(x - col, y - row) for x, y in polygon], fill=255)
    mask = mask.filter(ImageFilter.MaxFilter(5))
    background = Image.new("RGBA", rgba.size, "white")
    pixels = Image.alpha_composite(background, rgba).convert("RGB")
    masked = Image.new("RGB", pixels.size, "white")
    masked.paste(pixels, mask=mask)

    if abs(angle) >= 0.5:
        masked = masked.rotate(
            angle, Image.Resampling.BICUBIC, expand=True, fillcolor="white"
        )
        mask = mask.rotate(angle, Image.Resampling.BICUBIC, expand=True)
    box = mask.getbbox()
    if box is None:
        return None

    crop = ImageOps.expand(masked.crop(box), border=_MARGIN, fill="white")
    crop.thumbnail((3200, 640), Image.Resampling.LANCZOS)
    result = BytesIO()
    crop.save(result, format="PNG")
    return result.getvalue()

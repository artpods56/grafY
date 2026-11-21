"""Read the pixels for one TIFF polygon and prepare a single OCR line."""

from io import BytesIO
from math import atan2, ceil, degrees, floor, hypot

from PIL import Image, ImageDraw, ImageFilter, ImageOps
from shapely import Polygon

from grafy_core.node_context import UserFacingNodeError
from grafy_core.text_regions import PixelPolygon, TiffPage

CROP_MARGIN = 4
NATIVE_CROP_PIXEL_LIMIT = 1_000_000
_MAX_STITCH_READS = 64


def crop_pixels(polygon: PixelPolygon, *, margin: int = CROP_MARGIN) -> int:
    """What one read of this polygon costs the TIFF reader, in pixels.

    The reader crops the axis-aligned box around the polygon plus a margin, so a
    long polygon tilted off the axes costs much more than its own area: a label run
    of a few hundred pixels on each side is a million-pixel read.
    """

    xs, ys = zip(*polygon)
    width = ceil(max(xs)) - floor(min(xs)) + 2 * margin
    height = ceil(max(ys)) - floor(min(ys)) + 2 * margin
    return width * height


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


async def _read_window(
    page: TiffPage, *, col: int, row: int, width: int, height: int
) -> Image.Image:
    png = await page.read(col=col, row=row, width=width, height=height)
    with Image.open(BytesIO(png)) as source:
        return source.convert("RGBA")


async def _read_rect(
    page: TiffPage, *, col: int, row: int, width: int, height: int, where: str
) -> Image.Image:
    """The pixels of one page rectangle, in as many native reads as it takes.

    The tiler serves at most `NATIVE_CROP_PIXEL_LIMIT` pixels per window, and that
    bound belongs to it, so a longer label is read in full-width strips and pasted
    back into one image. The strips abut exactly: PNG is lossless and no strip
    overlaps another, so the assembled rectangle is the same pixels a single read
    would have returned and everything downstream cannot tell the difference.
    """

    if width * height <= NATIVE_CROP_PIXEL_LIMIT:
        return await _read_window(page, col=col, row=row, width=width, height=height)

    strip = NATIVE_CROP_PIXEL_LIMIT // height
    reads = ceil(width / strip) if strip >= 1 else 0
    if reads < 1 or reads > _MAX_STITCH_READS:
        raise UserFacingNodeError(
            f"{where} measures {width} x {height} = {width * height:,} pixels, which "
            f"cannot be assembled from reads of {NATIVE_CROP_PIXEL_LIMIT:,} pixels."
        )

    canvas = Image.new("RGBA", (width, height))
    for offset in range(0, width, strip):
        part = min(strip, width - offset)
        canvas.paste(
            await _read_window(
                page, col=col + offset, row=row, width=part, height=height
            ),
            (offset, 0),
        )
    return canvas


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
    col, row = max(0, left - CROP_MARGIN), max(0, top - CROP_MARGIN)
    width = min(page.width, right + CROP_MARGIN) - col
    height = min(page.height, bottom + CROP_MARGIN) - row

    rgba = await _read_rect(
        page,
        col=col,
        row=row,
        width=width,
        height=height,
        where=f"A single label at x {left}-{right}, y {top}-{bottom}",
    )
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

    crop = ImageOps.expand(masked.crop(box), border=CROP_MARGIN, fill="white")
    crop.thumbnail((3200, 640), Image.Resampling.LANCZOS)
    result = BytesIO()
    crop.save(result, format="PNG")
    return result.getvalue()

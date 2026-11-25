"""Contact-sheet image packer for batched vision LLM region OCR."""

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Final

from PIL import Image, ImageDraw, ImageFont

SHEET_FORMAT_VERSION: Final = "contact-sheet@1"
MAX_CROP_BYTES: Final = 4 * 1024 * 1024

_SHEET_MARGIN: Final = 12
_CELL_GAP: Final = 12
_CELL_PADDING: Final = 6
_BORDER_WIDTH: Final = 1
_BADGE_GAP: Final = 6
_MIN_BADGE_WIDTH: Final = 28
_MIN_BADGE_HEIGHT: Final = 24
_MIN_CROP_HEIGHT: Final = 40
_BADGE_FONT_SIZE: Final = 18

_BACKGROUND_COLOR: Final = (255, 255, 255)
_BORDER_COLOR: Final = (34, 34, 34)
_BADGE_FILL: Final = (17, 17, 17)
_BADGE_TEXT_COLOR: Final = (255, 255, 255)


class CropSheetError(ValueError):
    """A crop image cannot be decoded or packed onto a contact sheet."""


@dataclass(frozen=True, slots=True)
class PackedCropSheet:
    """One rendered contact sheet and the original crop indices in 1..K order."""

    png_bytes: bytes
    indices: tuple[int, ...]
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _PreparedCrop:
    index: int
    image: Image.Image


@dataclass(frozen=True, slots=True)
class _PlacedCell:
    index: int
    sheet_id: int
    image: Image.Image
    x: int
    y: int
    width: int
    height: int
    badge_width: int


def _load_badge_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=_BADGE_FONT_SIZE)
    except TypeError:
        return ImageFont.load_default()


def _badge_width(max_id: int, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1), _BACKGROUND_COLOR))
    left, _, right, _ = probe.textbbox((0, 0), str(max_id), font=font)
    text_width = int(right - left)
    return max(_MIN_BADGE_WIDTH, text_width + 12)


def _cell_dimensions(
    crop_width: int, crop_height: int, badge_width: int
) -> tuple[int, int]:
    inner_width = badge_width + _BADGE_GAP + crop_width
    inner_height = max(_MIN_BADGE_HEIGHT, crop_height)
    cell_width = inner_width + 2 * (_CELL_PADDING + _BORDER_WIDTH)
    cell_height = inner_height + 2 * (_CELL_PADDING + _BORDER_WIDTH)
    return cell_width, cell_height


def _decode_crop(raw: bytes, *, index: int, max_crop_width: int, max_crop_height: int) -> Image.Image:
    if len(raw) > MAX_CROP_BYTES:
        raise CropSheetError(f"Text crop {index + 1} exceeds the {MAX_CROP_BYTES}-byte limit")
    try:
        with Image.open(BytesIO(raw)) as opened:
            if "A" in opened.getbands():
                rgba = opened.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = opened.convert("RGB")
    except Exception as exc:
        raise CropSheetError(f"Could not decode text crop {index + 1} as an image") from exc

    width, height = image.size
    if width < 1 or height < 1:
        raise CropSheetError(f"Text crop {index + 1} is empty")

    # Upscale very small crops slightly so labels stay legible, without overflowing the sheet.
    if height < _MIN_CROP_HEIGHT:
        scale = min(_MIN_CROP_HEIGHT / height, max_crop_width / width, max_crop_height / height)
        if scale > 1.0:
            new_width = max(1, round(width * scale))
            new_height = max(1, round(height * scale))
            image = image.resize((new_width, new_height), Image.Resampling.BICUBIC)
            width, height = image.size

    # Bound unusually large single crops so they still fit inside one contact-sheet cell.
    if width > max_crop_width or height > max_crop_height:
        scale = min(max_crop_width / width, max_crop_height / height)
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    return image


def _render_sheet(
    cells: Sequence[_PlacedCell],
    *,
    used_width: int,
    used_height: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> PackedCropSheet:
    canvas = Image.new("RGB", (used_width, used_height), _BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)

    for cell in cells:
        x0 = cell.x
        y0 = cell.y
        x1 = x0 + cell.width - 1
        y1 = y0 + cell.height - 1
        draw.rectangle((x0, y0, x1, y1), fill=_BACKGROUND_COLOR, outline=_BORDER_COLOR, width=_BORDER_WIDTH)

        inner_x = x0 + _BORDER_WIDTH + _CELL_PADDING
        inner_y = y0 + _BORDER_WIDTH + _CELL_PADDING
        inner_h = cell.height - 2 * (_BORDER_WIDTH + _CELL_PADDING)

        badge_y0 = inner_y + (inner_h - _MIN_BADGE_HEIGHT) // 2
        badge_x1 = inner_x + cell.badge_width - 1
        badge_y1 = badge_y0 + _MIN_BADGE_HEIGHT - 1
        draw.rectangle((inner_x, badge_y0, badge_x1, badge_y1), fill=_BADGE_FILL)

        label = str(cell.sheet_id)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        text_w = right - left
        text_h = bottom - top
        text_x = inner_x + (cell.badge_width - text_w) / 2 - left
        text_y = badge_y0 + (_MIN_BADGE_HEIGHT - text_h) / 2 - top
        draw.text((text_x, text_y), label, fill=_BADGE_TEXT_COLOR, font=font)

        crop_x = inner_x + cell.badge_width + _BADGE_GAP
        crop_y = inner_y + (inner_h - cell.image.height) // 2
        canvas.paste(cell.image, (crop_x, crop_y))

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return PackedCropSheet(
        png_bytes=buffer.getvalue(),
        indices=tuple(cell.index for cell in cells),
        width=used_width,
        height=used_height,
    )


def pack_crop_sheets(
    crops: Sequence[bytes],
    *,
    max_crops: int,
    max_edge: int,
) -> list[PackedCropSheet]:
    """Row-pack text crops onto bounded PNG contact sheets numbered 1..K per sheet."""

    if not crops:
        return []
    if max_crops < 1:
        raise ValueError("max_crops must be at least 1")
    if max_edge < 128:
        raise ValueError("max_edge must be at least 128")

    font = _load_badge_font()
    badge_w = _badge_width(max_crops, font)
    cell_chrome_w = 2 * (_CELL_PADDING + _BORDER_WIDTH) + badge_w + _BADGE_GAP
    cell_chrome_h = 2 * (_CELL_PADDING + _BORDER_WIDTH)
    max_crop_width = max_edge - 2 * _SHEET_MARGIN - cell_chrome_w
    max_crop_height = max_edge - 2 * _SHEET_MARGIN - cell_chrome_h
    if max_crop_width < 16 or max_crop_height < 16:
        raise ValueError("max_edge is too small to fit a crop cell")

    prepared = [
        _PreparedCrop(
            index=index,
            image=_decode_crop(
                raw,
                index=index,
                max_crop_width=max_crop_width,
                max_crop_height=max_crop_height,
            ),
        )
        for index, raw in enumerate(crops)
    ]

    sheets: list[PackedCropSheet] = []
    placed: list[_PlacedCell] = []
    cur_x = _SHEET_MARGIN
    cur_y = _SHEET_MARGIN
    row_height = 0
    max_right = 0

    def flush() -> None:
        nonlocal placed, cur_x, cur_y, row_height, max_right
        if not placed:
            return
        used_width = max_right + _SHEET_MARGIN
        used_height = cur_y + row_height + _SHEET_MARGIN
        sheets.append(
            _render_sheet(
                placed,
                used_width=used_width,
                used_height=used_height,
                font=font,
            )
        )
        placed = []
        cur_x = _SHEET_MARGIN
        cur_y = _SHEET_MARGIN
        row_height = 0
        max_right = 0

    for item in prepared:
        cell_w, cell_h = _cell_dimensions(item.image.width, item.image.height, badge_w)

        if len(placed) >= max_crops:
            flush()

        # Try placing on the current row.
        if placed and cur_x + cell_w + _SHEET_MARGIN > max_edge:
            next_y = cur_y + row_height + _CELL_GAP
            if next_y + cell_h + _SHEET_MARGIN > max_edge:
                flush()
            else:
                cur_x = _SHEET_MARGIN
                cur_y = next_y
                row_height = 0
        elif placed and cur_y + max(row_height, cell_h) + _SHEET_MARGIN > max_edge:
            flush()

        sheet_id = len(placed) + 1
        placed.append(
            _PlacedCell(
                index=item.index,
                sheet_id=sheet_id,
                image=item.image,
                x=cur_x,
                y=cur_y,
                width=cell_w,
                height=cell_h,
                badge_width=badge_w,
            )
        )
        max_right = max(max_right, cur_x + cell_w)
        cur_x += cell_w + _CELL_GAP
        row_height = max(row_height, cell_h)

    flush()
    return sheets

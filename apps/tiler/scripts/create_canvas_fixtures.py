"""Create synthetic archival scans through GDAL, never downloaded private records.

Run in the tiler environment: python scripts/create_canvas_fixtures.py OUTPUT_DIR.
"""

import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont
from rasterio.enums import ColorInterp

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
scan = Image.new("RGB", (1504, 1024), (236, 222, 189))
draw = ImageDraw.Draw(scan)
font = ImageFont.load_default(size=28)
draw.text(
    (75, 45), "SYNTHETIC ARCHIVE — Parish register, 1894", font=font, fill=(63, 48, 38)
)
for row in range(18):
    y = 130 + row * 45
    draw.line((70, y, 1430, y), fill=(119, 94, 69), width=2)
    draw.text(
        (90, y + 6),
        f"{row + 1:03d}     November {row + 1:02d}       Historical scan test       Register folio {row + 1}",
        font=font,
        fill=(69, 55, 47),
    )
for x in (70, 230, 520, 1020, 1430):
    draw.line((x, 125, x, 950), fill=(119, 94, 69), width=2)

rgb = np.asarray(scan.resize((12032, 8192)))
with rasterio.open(
    output / "register-rgb.tif",
    "w",
    driver="GTiff",
    width=12032,
    height=8192,
    count=3,
    dtype="uint8",
    tiled=True,
    compress="deflate",
) as ds:
    ds.write(rgb.transpose(2, 0, 1))
    ds.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
del rgb

gray = np.asarray(scan.convert("L").resize((3008, 2048)), dtype=np.uint16) * 257
with rasterio.open(
    output / "register-gray16.tif",
    "w",
    driver="GTiff",
    width=3008,
    height=2048,
    count=1,
    dtype="uint16",
    tiled=True,
    compress="deflate",
) as ds:
    ds.write(gray, 1)

for page in range(3):
    frame = scan.copy()
    ImageDraw.Draw(frame).text(
        (75, 980),
        f"PAGE {page + 1} — synthetic verification fixture",
        font=font,
        fill=(100, 30, 30),
    )
    with rasterio.open(
        output / "register-pages.tif",
        "w",
        driver="GTiff",
        width=1504,
        height=1024,
        count=3,
        dtype="uint8",
        tiled=True,
        compress="deflate",
        APPEND_SUBDATASET="YES" if page else "NO",
    ) as ds:
        ds.write(np.asarray(frame).transpose(2, 0, 1))
        ds.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)

rgba = np.asarray(scan.convert("RGBA")).copy()
rgba[:100, :, 3] = 0
rgba[:, :100, 3] = 0
with rasterio.open(
    output / "register-alpha.tif",
    "w",
    driver="GTiff",
    width=1504,
    height=1024,
    count=4,
    dtype="uint8",
    tiled=True,
    compress="deflate",
) as ds:
    ds.write(rgba.transpose(2, 0, 1))
    ds.colorinterp = (
        ColorInterp.red,
        ColorInterp.green,
        ColorInterp.blue,
        ColorInterp.alpha,
    )
for path in sorted(output.glob("*.tif")):
    with rasterio.open(path) as ds:
        print(
            path.name,
            ds.width,
            ds.height,
            ds.dtypes,
            "pages",
            max(1, len(ds.subdatasets)),
        )

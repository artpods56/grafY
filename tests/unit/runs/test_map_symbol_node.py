from collections.abc import Sequence
from io import BytesIO
from uuid import UUID, uuid4

from PIL import Image, ImageDraw

from grafy_core.artifacts import NoConfig
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext
from grafy_core.node_ports import Ref
from grafy_core.text_regions import TextReading, TextRecognizer, TextRegion, TiffPage
from grafy_workbench.ocr.label_nodes import (
    FilterReadingsConfig,
    FilterReadingsInput,
    FilterReadingsNode,
    PlacesTableInput,
    PlacesTableNode,
    PrepareLabelsConfig,
    PrepareLabelsInput,
    PrepareMapLabelsNode,
)
from grafy_workbench.ocr.symbol_node import (
    FilterMapSymbolsConfig,
    FilterMapSymbolsInput,
    FilterMapSymbolsNode,
)
from grafy_workbench.ocr.text_regions import TiffPixelWindow, TiffTextRegions
from grafy_workbench.ocr.tiff_recognition import ReadTiffTextNode, RecognizeInput


async def test_map_nodes_drop_a_symbol_before_ocr_and_pass_through_place_coordinates():
    image = Image.new("RGB", (180, 220), "#dedbb5")
    draw = ImageDraw.Draw(image)
    for left in range(40, 111, 13):
        draw.arc((left, 45, left + 10, 72), 180, 360, fill="#557b42", width=4)
    draw.text((40, 145), "MAKHOVO", fill="#292020", font_size=18)
    context = NodeExecutionContext(workspace_id=uuid4())
    source = Ref[TiffFile](
        artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
    )
    symbol = TextRegion(polygon=[(36, 41), (116, 41), (116, 73), (36, 73)])
    label = TextRegion(polygon=[(36, 141), (116, 141), (116, 173), (36, 173)])
    window = TiffPixelWindow(page=2, col=20, row=25, width=150, height=175)
    detected = TiffTextRegions(source=source, window=window, regions=[symbol, label])
    requested: list[tuple[int, int, int, int]] = []

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        requested.append((col, row, width, height))
        png = BytesIO()
        image.crop((col, row, col + width, row + height)).save(png, format="PNG")
        return png.getvalue()

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        assert (workspace_id, artifact_id, page) == (
            context.workspace_id,
            source.artifact_id,
            2,
        )
        return TiffPage(180, 220, read, source_sha256="0" * 64, page=page)

    class Recognizer(TextRecognizer):
        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            assert len(crops) == 1
            return [TextReading(text="сел: Махово", confidence=0.81, model="test")]

    filtered = await FilterMapSymbolsNode(open_page).run(
        context, FilterMapSymbolsConfig(), FilterMapSymbolsInput(regions=detected)
    )
    assert requested == [(20, 25, 113, 65), (20, 125, 113, 65)]
    assert filtered.regions == TiffTextRegions(
        source=source, window=window, regions=[label]
    )
    prepared = await PrepareMapLabelsNode().run(
        context,
        PrepareLabelsConfig(min_height_ratio=0),
        PrepareLabelsInput(regions=filtered.regions),
    )
    recognized = await ReadTiffTextNode(open_page).run(
        context,
        NoConfig(),
        RecognizeInput(regions=prepared.regions, recognizer=Recognizer()),
    )
    readings = await FilterReadingsNode().run(
        context, FilterReadingsConfig(), FilterReadingsInput(text=recognized.text)
    )
    result = await PlacesTableNode().run(
        context, NoConfig(), PlacesTableInput(text=readings.text)
    )
    assert [
        (row["name"], row["page"], row["x"], row["y"]) for row in result.places.rows
    ] == [("Махово", 2, 76.0, 157.0)]

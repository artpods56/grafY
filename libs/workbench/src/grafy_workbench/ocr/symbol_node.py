"""Optional pixel-based filtering before map label spans are assembled."""

from asyncio import to_thread
from typing import final, override

from pydantic import Field

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.text_regions import TextRegion, TiffPage, TiffPageOpener

from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.map_symbol_filter import CONTEXT_PIXELS, is_map_symbol
from grafy_workbench.ocr.text_regions import TiffTextRegions
from grafy_workbench.ocr.tiff_label_crop import NATIVE_CROP_PIXEL_LIMIT


class FilterMapSymbolsConfig(NodeConfig):
    threshold: float = Field(
        default=0.90,
        ge=0.5,
        le=1.0,
        title="Minimum symbol score",
        description=(
            "Drop regions at or above this score. "
            "The experimental classifier was fitted on one historical map."
        ),
    )


class FilterMapSymbolsInput(NodeInput):
    regions: TiffTextRegions = Field(title="Text regions")


class FilterMapSymbolsOutput(NodeOutput):
    regions: TiffTextRegions = Field(title="Text regions")


async def _is_symbol(page: TiffPage, region: TextRegion, threshold: float) -> bool:
    xs, ys = zip(*region.polygon, strict=True)
    if max(xs) > page.width or max(ys) > page.height:
        raise UserFacingNodeError("A text polygon extends outside its source TIFF page")

    col = max(0, round(min(xs)) - CONTEXT_PIXELS)
    row = max(0, round(min(ys)) - CONTEXT_PIXELS)
    right = min(page.width, round(max(xs)) + 1 + CONTEXT_PIXELS)
    bottom = min(page.height, round(max(ys)) + 1 + CONTEXT_PIXELS)
    width, height = right - col, bottom - row
    if width * height > NATIVE_CROP_PIXEL_LIMIT:
        return False

    png = await page.read(col=col, row=row, width=width, height=height)
    local_polygon = [(x - col, y - row) for x, y in region.polygon]
    return await to_thread(is_map_symbol, png, local_polygon, threshold=threshold)


@OCR.node(
    operator_id="ocr.filter_tiff_map_symbols",
    version=1,
    title="Filter map symbols",
    factory=lambda context: FilterMapSymbolsNode(context.open_tiff_page),
)
@final
class FilterMapSymbolsNode(
    Node[FilterMapSymbolsConfig, FilterMapSymbolsInput, FilterMapSymbolsOutput]
):
    """Experimental filter for symbols mistaken for text on historical maps."""

    def __init__(self, open_page: TiffPageOpener | None) -> None:
        self._open_page = open_page

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: FilterMapSymbolsConfig,
        inputs: FilterMapSymbolsInput,
        /,
    ) -> FilterMapSymbolsOutput:
        detected = inputs.regions
        total = len(detected.regions)
        if not total or config.threshold == 1:
            return FilterMapSymbolsOutput(regions=detected)
        if self._open_page is None:
            raise UserFacingNodeError("TIFF window reading is unavailable")
        page = await self._open_page(
            context.workspace_id, detected.source.artifact_id, page=detected.window.page
        )
        kept: list[TextRegion] = []
        await context.progress("Filtering map symbols", current=0, total=total)
        for index, region in enumerate(detected.regions, 1):
            if not await _is_symbol(page, region, config.threshold):
                kept.append(region)
            if index % 32 == 0 or index == total:
                await context.progress(
                    "Filtering map symbols", current=index, total=total
                )
        return FilterMapSymbolsOutput(
            regions=TiffTextRegions(
                source=detected.source, window=detected.window, regions=kept
            )
        )

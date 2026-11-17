from typing import Annotated, final, override

from pydantic import Field

from grafy_core.artifact_contracts import IMAGE_REGIONS, ImageRegionSet, MarkdownValue
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.declared_values import note_declaration
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.ocr_contracts import OcrReader, OcrResult, check_ocr_result
from grafy_core.table_contracts import Table

import grafy_workbench.table.plugin as _table_plugin
import grafy_workbench.text.nodes as _text_nodes
from grafy_workbench.ocr.declaration import OCR

_ = (_table_plugin.__name__, _text_nodes.__name__)
# Image regions are owned by the image plugin; note the type so this output
# derives without importing that plugin from a builtin family.
note_declaration(ImageRegionSet, IMAGE_REGIONS.key)


class OcrConfig(NodeConfig):
    pass


class OcrInput(NodeInput):
    document: Annotated[
        RasterImage | PdfFile,
        Field(
            title="Scan or PDF",
            description="One scanned page or a PDF to read.",
        ),
    ]
    reader: Annotated[
        OcrReader,
        Field(
            title="Reader",
            description="An OCR provider that reads the document.",
        ),
    ]


class OcrOutput(NodeOutput):
    markdown: Annotated[
        MarkdownValue,
        Field(
            title="Transcription",
            description="The reading, with pages kept in order.",
        ),
    ]
    blocks: Annotated[
        Table | None,
        Field(
            default=None,
            title="Text blocks",
            description=(
                "One row per piece the reader found: page, kind of region, "
                "text, and box."
            ),
        ),
    ] = None
    regions: Annotated[
        ImageRegionSet | None,
        Field(
            default=None,
            title="Boxes on the page",
            description="Where each region sits on the page, in pixels.",
        ),
    ] = None


@OCR.node(
    operator_id="ocr.read",
    version=1,
    title="OCR",
)
@final
class OcrNode(Node[OcrConfig, OcrInput, OcrOutput]):
    """Reads a scan or PDF through a connected OCR provider."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: OcrConfig,
        inputs: OcrInput,
        /,
    ) -> OcrOutput:
        result: OcrResult = await inputs.reader.read(inputs.document)
        unsupported = check_ocr_result(inputs.reader, result)
        if unsupported:
            context.output_metadata["unsupported_outputs"] = unsupported
        return OcrOutput(
            markdown=result.markdown,
            blocks=result.blocks,
            regions=result.regions,
        )

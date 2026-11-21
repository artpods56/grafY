"""Nodes that turn detected label boxes into place names and a places table."""

from typing import Annotated, final, override

from pydantic import Field

from grafy_core.artifacts import NoConfig, NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import Node, NodeExecutionContext, Plugs
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType

from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.label_spans import (
    filter_readings,
    places_table,
    prepare_labels,
)
from grafy_workbench.ocr.tiff_recognition import TiffRecognizedText
from grafy_workbench.ocr.text_regions import TiffTextRegions
import grafy_workbench.table.plugin as _table_plugin

# The table family notes Table as table.data, which these ports derive from.
_ = _table_plugin.__name__


class PrepareLabelsConfig(NodeConfig):
    min_height_ratio: float = Field(
        title="Minimum height ratio",
        default=0.55,
        ge=0,
        le=1,
        description=(
            "Drop a box shorter than this fraction of the sheet's letter height "
            "when it is also not elongated. Trees and hatching are smaller than "
            "the lettering."
        ),
    )
    max_gap_heights: float = Field(
        title="Maximum join gap",
        default=1.5,
        ge=0,
        le=8,
        description=(
            "Join boxes on the same line when the gap is at most this many letter "
            "heights."
        ),
    )
    max_baseline_offset: float = Field(
        title="Maximum baseline offset",
        default=0.45,
        ge=0,
        le=2,
        json_schema_extra={"x-grafy-advanced": True},
        description=(
            "How far above or below a shared baseline two boxes may sit, in letter "
            "heights, and still be joined."
        ),
    )
    max_angle_degrees: float = Field(
        title="Maximum angle difference",
        default=12,
        ge=0,
        le=45,
        json_schema_extra={"x-grafy-advanced": True},
        description=(
            "How much two boxes may be tilted relative to each other, in degrees, "
            "and still be joined."
        ),
    )


class PrepareLabelsInput(NodeInput):
    regions: TiffTextRegions = Field(title="Text regions")


class PrepareLabelsOutput(NodeOutput):
    regions: TiffTextRegions = Field(title="Text regions")


@OCR.node(
    operator_id="ocr.prepare_tiff_labels",
    version=1,
    title="Prepare map labels",
)
@final
class PrepareMapLabelsNode(
    Node[PrepareLabelsConfig, PrepareLabelsInput, PrepareLabelsOutput]
):
    """Drops symbol-sized boxes and joins the boxes of one name into one span."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: PrepareLabelsConfig,
        inputs: PrepareLabelsInput,
        /,
    ) -> PrepareLabelsOutput:
        detected = inputs.regions
        return PrepareLabelsOutput(
            regions=TiffTextRegions(
                source=detected.source,
                window=detected.window,
                regions=prepare_labels(
                    detected.regions,
                    min_height_ratio=config.min_height_ratio,
                    max_gap_heights=config.max_gap_heights,
                    max_baseline_offset=config.max_baseline_offset,
                    max_angle_degrees=config.max_angle_degrees,
                ),
            )
        )


class FilterReadingsConfig(NodeConfig):
    min_confidence: float = Field(
        title="Minimum confidence",
        default=0.4,
        ge=0,
        le=1,
        description=(
            "Drop a reading the recognizer is less sure about than this. A reading "
            "with no confidence keeps its place."
        ),
    )
    min_letters: int = Field(
        title="Minimum letters",
        default=3,
        ge=1,
        le=40,
        description="Drop a reading with fewer letters than this.",
    )


class FilterReadingsInput(NodeInput):
    text: TiffRecognizedText = Field(title="Recognized text")


class FilterReadingsOutput(NodeOutput):
    text: TiffRecognizedText = Field(title="Recognized text")


@OCR.node(
    operator_id="ocr.filter_tiff_readings",
    version=1,
    title="Filter recognized labels",
)
@final
class FilterReadingsNode(
    Node[FilterReadingsConfig, FilterReadingsInput, FilterReadingsOutput]
):
    """Drops readings that are not name-like."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: FilterReadingsConfig,
        inputs: FilterReadingsInput,
        /,
    ) -> FilterReadingsOutput:
        recognized = inputs.text
        return FilterReadingsOutput(
            text=TiffRecognizedText(
                source=recognized.source,
                window=recognized.window,
                regions=filter_readings(
                    recognized.regions,
                    min_confidence=config.min_confidence,
                    min_letters=config.min_letters,
                ),
            )
        )


class PlacesTableInput(NodeInput):
    text: TiffRecognizedText = Field(title="Recognized text")


class PlacesTableOutput(NodeOutput):
    places: Table = Field(title="Places")


@OCR.node(
    operator_id="ocr.places_table",
    version=1,
    title="Map places table",
)
@final
class PlacesTableNode(Node[NoConfig, PlacesTableInput, PlacesTableOutput]):
    """Writes one row per recognized place, with its position on the page."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: PlacesTableInput,
        /,
    ) -> PlacesTableOutput:
        return PlacesTableOutput(places=places_table(inputs.text))


class CollectMapPlacesInput(NodeInput):
    readings: Annotated[
        list[TiffRecognizedText], Plugs(variadic=True, instance=True, spare=True)
    ] = Field(min_length=1, title="Recognized TIFF sheets")


@OCR.node(
    operator_id="ocr.collect_map_places",
    version=1,
    title="Collect map places from TIFF sheets",
)
@final
class CollectMapPlacesNode(Node[NoConfig, CollectMapPlacesInput, PlacesTableOutput]):
    """Collect whole-sheet OCR readings without losing their source pixel coordinates."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: CollectMapPlacesInput,
        /,
    ) -> PlacesTableOutput:
        sheets = [
            (reading.source.artifact_id, places_table(reading))
            for reading in inputs.readings
        ]
        columns = [
            *sheets[0][1].columns,
            TableColumn(
                id="source_artifact_id",
                title="Source TIFF",
                value_type=TableValueType.TEXT,
            ),
        ]
        rows: list[dict[str, TableValue]] = []
        for artifact_id, sheet in sheets:
            source_id = str(artifact_id)
            rows.extend({**row, "source_artifact_id": source_id} for row in sheet.rows)
        return PlacesTableOutput(places=Table(columns=columns, rows=rows))

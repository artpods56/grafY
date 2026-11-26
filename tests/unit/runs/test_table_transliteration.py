from uuid import uuid4

import pytest

from grafy_core.artifact_contracts import MARKDOWN, TEXT_VALUE, MarkdownValue
from grafy_core.artifacts import ArtifactTypeKey, NoConfig, NodeInput, NodeOutput
from grafy_core.contracts.ocr import TextReading
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.node_ports import (
    ExclusiveGroup,
    NodeContractError,
    Ref,
    RequiresInput,
)
from grafy_core.nodes import Node
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_plugin_map_toponyms.text_regions import TiffPixelWindow
from grafy_plugin_map_toponyms.tiff_recognition import (
    TiffRecognizedRegion,
    TiffRecognizedText,
)
from grafy_plugin_map_toponyms.transliteration import (
    TransliterateConfig,
    TransliterateCyrillicNode,
    TransliterateCyrillicTextNode,
    TransliterateInput,
    TransliterateTextInput,
    transliterate_cyrillic,
)


@pytest.mark.parametrize(
    ("original", "latin"),
    [
        ("Бѣлыничи", "Belynichi"),
        ("Пропойскъ", "Propoysk"),
        ("ЧАУСЫ", "CHAUSY"),
        ("Чауссы", "Chaussy"),
        ("м. Кричевъ / Krychaw", "m. Krichev / Krychaw"),
        ("Іўе — Київ", "Iue — Kiyiv"),
    ],
)
def test_transliterates_old_and_modern_cyrillic(original: str, latin: str) -> None:
    assert transliterate_cyrillic(original) == latin


async def test_table_keeps_original_spellings_and_coordinates() -> None:
    table = Table(
        columns=[
            TableColumn(id="seat", title="Seat", value_type=TableValueType.TEXT),
            TableColumn(id="page", title="Page", value_type=TableValueType.INTEGER),
        ],
        rows=[{"seat": "Кричевъ", "page": 8}, {"seat": None, "page": 9}],
    )
    result = await TransliterateCyrillicNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        TransliterateConfig(source_column="seat", output_column="seat_latin"),
        TransliterateInput(table=table),
    )
    assert result.table.rows == [
        {"seat": "Кричевъ", "page": 8, "seat_latin": "Krichev"},
        {"seat": None, "page": 9, "seat_latin": None},
    ]
    assert [column.id for column in result.table.columns] == [
        "seat",
        "page",
        "seat_latin",
    ]


async def test_transliteration_does_not_overwrite_the_source_column() -> None:
    table = Table(columns=[TableColumn(id="name", title="Name")], rows=[])
    with pytest.raises(UserFacingNodeError, match="already exists"):
        await TransliterateCyrillicNode().run(
            NodeExecutionContext(workspace_id=uuid4()),
            TransliterateConfig(output_column="name"),
            TransliterateInput(table=table),
        )


def _tiff_source() -> Ref[TiffFile]:
    return Ref[TiffFile](
        artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
    )


def test_text_node_declares_exclusive_lanes_and_gated_outputs() -> None:
    text_in = TransliterateCyrillicTextNode.input_contract.ports["text"]
    recognized_in = TransliterateCyrillicTextNode.input_contract.ports["recognized"]
    assert text_in.accepts == MARKDOWN.key
    assert text_in.also_accepts == (TEXT_VALUE.key,)
    assert not text_in.required
    assert text_in.exclusive_group == "source"
    assert recognized_in.accepts == ArtifactTypeKey("ocr.tiff_recognized_text", 1)
    assert recognized_in.also_accepts == ()
    assert not recognized_in.required
    assert recognized_in.exclusive_group == "source"

    text_out = TransliterateCyrillicTextNode.output_contract.ports["text"]
    recognized_out = TransliterateCyrillicTextNode.output_contract.ports["recognized"]
    assert text_out.required
    assert text_out.requires_input is None
    assert not recognized_out.required
    assert recognized_out.requires_input == "recognized"


async def test_rewrites_markdown_and_keeps_markup() -> None:
    result = await TransliterateCyrillicTextNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        NoConfig(),
        TransliterateTextInput(text=MarkdownValue(markdown="# Бѣлыничи\n\nм. Кричевъ")),
    )
    assert result.text is not None
    assert result.text.markdown == "# Belynichi\n\nm. Krichev"
    assert result.recognized is None


async def test_rewrites_plain_text() -> None:
    result = await TransliterateCyrillicTextNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        NoConfig(),
        TransliterateTextInput(text="Іўе — Київ"),
    )
    assert result.text is not None
    assert result.text.markdown == "Iue — Kiyiv"
    assert result.recognized is None


async def test_rewrites_recognized_tiff_readings_and_keeps_boxes() -> None:
    source = _tiff_source()
    window = TiffPixelWindow(page=2, col=10, row=20, width=200, height=80)
    recognized = TiffRecognizedText(
        source=source,
        window=window,
        regions=[
            TiffRecognizedRegion(
                polygon=[(10, 20), (40, 20), (40, 40), (10, 40)],
                text="детектор",
                score=0.9,
                reading=TextReading(text="Бѣлыничи", confidence=0.81, model="paddle"),
            ),
            TiffRecognizedRegion(
                polygon=[(50, 20), (90, 20), (90, 40), (50, 40)],
                reading=None,
            ),
            TiffRecognizedRegion(
                polygon=[(100, 20), (140, 20), (140, 40), (100, 40)],
                reading=TextReading(text="Кричевъ", confidence=0.92, model="paddle"),
            ),
        ],
    )
    result = await TransliterateCyrillicTextNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        NoConfig(),
        TransliterateTextInput(recognized=recognized),
    )
    assert result.text.markdown == "Belynichi Krichev"
    assert result.recognized is not None
    assert result.recognized.source == source
    assert result.recognized.window == window
    assert result.recognized.regions[0].polygon == recognized.regions[0].polygon
    assert result.recognized.regions[0].text == "detektor"
    assert result.recognized.regions[0].reading is not None
    assert result.recognized.regions[0].reading.text == "Belynichi"
    assert result.recognized.regions[0].reading.confidence == 0.81
    assert result.recognized.regions[0].reading.model == "paddle"
    assert result.recognized.regions[1].reading is None
    assert result.recognized.regions[2].reading is not None
    assert result.recognized.regions[2].reading.text == "Krichev"


async def test_requires_exactly_one_input() -> None:
    with pytest.raises(UserFacingNodeError, match="Connect Text or Recognized text"):
        await TransliterateCyrillicTextNode().run(
            NodeExecutionContext(workspace_id=uuid4()),
            NoConfig(),
            TransliterateTextInput(),
        )

    recognized = TiffRecognizedText(
        source=_tiff_source(),
        window=TiffPixelWindow(page=0, col=0, row=0, width=10, height=10),
        regions=[],
    )
    with pytest.raises(UserFacingNodeError, match="not both"):
        await TransliterateCyrillicTextNode().run(
            NodeExecutionContext(workspace_id=uuid4()),
            NoConfig(),
            TransliterateTextInput(text="Київ", recognized=recognized),
        )


def test_rejects_invalid_requires_input_and_exclusive_group_contracts() -> None:
    from typing import Annotated

    with pytest.raises(NodeContractError, match="at least two inputs"):

        class SoloGroupInput(NodeInput):
            text: Annotated[MarkdownValue | None, ExclusiveGroup("only")] = None

        class SoloGroupOutput(NodeOutput):
            text: MarkdownValue

        class _SoloNode(Node[NoConfig, SoloGroupInput, SoloGroupOutput]):
            async def run(self, context, config, inputs, /):  # type: ignore[override]
                raise NotImplementedError

    with pytest.raises(NodeContractError, match="not an artifact input"):

        class EmptyInput(NodeInput):
            pass

        class BadGateOutput(NodeOutput):
            text: Annotated[MarkdownValue | None, RequiresInput("missing")] = None

        class _BadGateNode(Node[NoConfig, EmptyInput, BadGateOutput]):
            async def run(self, context, config, inputs, /):  # type: ignore[override]
                raise NotImplementedError

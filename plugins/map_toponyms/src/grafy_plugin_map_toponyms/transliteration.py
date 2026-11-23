"""Append a Latin-script column for place-name comparison."""

import re
import unicodedata
from typing import Annotated, final, override

from pydantic import Field, StringConstraints

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType

from grafy_plugin_map_toponyms.declaration import MAP_TOPONYMS

_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "і": "i",
    "є": "ye",
    "ї": "yi",
    "ґ": "g",
    "ў": "u",
    "ѣ": "e",
    "ѳ": "f",
    "ѵ": "i",
}
_CYRILLIC_WORD = re.compile(r"[\u0400-\u052f\u1c80-\u1c8f]+")


def transliterate_cyrillic(text: str) -> str:
    def latin_word(match: re.Match[str]) -> str:
        word = match.group()
        upper = len(word) > 1 and word.isupper()
        letters: list[str] = []
        for letter in word:
            latin = _LATIN.get(letter.lower(), letter)
            if upper:
                latin = latin.upper()
            elif letter.isupper():
                latin = latin[:1].upper() + latin[1:]
            letters.append(latin)
        return "".join(letters)

    return _CYRILLIC_WORD.sub(latin_word, unicodedata.normalize("NFC", text))


type ColumnId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class TransliterateConfig(NodeConfig):
    source_column: ColumnId = Field(default="name", title="Source column ID")
    output_column: ColumnId = Field(default="name_latin", title="New column ID")


class TransliterateInput(NodeInput):
    table: Table = Field(title="Table")


class TransliterateOutput(NodeOutput):
    table: Table = Field(title="Transliterated table")


@MAP_TOPONYMS.node(
    operator_id="table.transliterate_cyrillic",
    version=1,
    title="Transliterate Cyrillic column",
)
@final
class TransliterateCyrillicNode(
    Node[TransliterateConfig, TransliterateInput, TransliterateOutput]
):
    """Add a Latin-script spelling beside the original Cyrillic text."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: TransliterateConfig,
        inputs: TransliterateInput,
        /,
    ) -> TransliterateOutput:
        table = inputs.table
        columns = {column.id: column for column in table.columns}
        if config.source_column not in columns:
            raise UserFacingNodeError(
                f"Source column {config.source_column!r} does not exist"
            )
        if config.output_column in columns:
            raise UserFacingNodeError(f"Column {config.output_column!r} already exists")

        rows: list[dict[str, TableValue]] = []
        for index, row in enumerate(table.rows, 1):
            value = row[config.source_column]
            if value is not None and not isinstance(value, str):
                raise UserFacingNodeError(
                    f"Row {index} in column {config.source_column!r} must contain text or null"
                )
            rows.append(
                {
                    **row,
                    config.output_column: transliterate_cyrillic(value)
                    if isinstance(value, str)
                    else None,
                }
            )
        column = TableColumn(
            id=config.output_column,
            title=config.output_column,
            value_type=TableValueType.TEXT,
        )
        return TransliterateOutput(
            table=Table(columns=[*table.columns, column], rows=rows)
        )

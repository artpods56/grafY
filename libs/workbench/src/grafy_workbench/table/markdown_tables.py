"""Extract structured tables from Markdown documents containing HTML or pipe tables."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import final, override

from pydantic import Field

from grafy_core.artifact_contracts import MarkdownValue
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType

import grafy_workbench.text.nodes as _text_nodes
from grafy_workbench.table.declaration import TABLES

_ = _text_nodes.__name__  # notes MarkdownValue before port derivation

_TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+\.\s+\S.{2,})\s*$")
_LEADER_DOTS_RE = re.compile(r"(?:\s*\.\s*){2,}$")
_INDEX_CELL_RE = re.compile(r"^\d+\.?$")
_PIPE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


@dataclass(slots=True)
class _RawCell:
    tag: str
    colspan: int
    rowspan: int
    text: str


@dataclass(slots=True)
class _ParsedGridRow:
    cells: list[str]
    all_th: bool
    is_banner: bool


@dataclass(slots=True)
class _PendingCell:
    tag: str
    colspan: int
    rowspan: int
    chunks: list[str] = field(default_factory=list)


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[_RawCell]]] = []
        self._table: list[list[_RawCell]] | None = None
        self._row: list[_RawCell] | None = None
        self._cell: _PendingCell | None = None

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower == "table":
            self._table = []
        elif lower == "tr" and self._table is not None:
            self._row = []
        elif lower in {"td", "th"} and self._row is not None:
            attr_map = dict(attrs)
            colspan = _parse_span(attr_map.get("colspan"))
            rowspan = _parse_span(attr_map.get("rowspan"))
            self._cell = _PendingCell(tag=lower, colspan=colspan, rowspan=rowspan)
        elif lower == "br" and self._cell is not None:
            self._cell.chunks.append(" ")

    @override
    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.chunks.append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"td", "th"} and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell.chunks).split())
            self._row.append(
                _RawCell(
                    tag=self._cell.tag,
                    colspan=self._cell.colspan,
                    rowspan=self._cell.rowspan,
                    text=text,
                )
            )
            self._cell = None
        elif lower == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif lower == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _parse_span(raw: str | None) -> int:
    if raw is None:
        return 1
    try:
        parsed = int(raw)
    except ValueError:
        return 1
    return max(1, parsed)


def _expand_html_rows(
    raw_rows: list[list[_RawCell]], *, min_columns: int
) -> list[_ParsedGridRow]:
    grid: list[_ParsedGridRow] = []
    carried_spans: dict[tuple[int, int], tuple[str, bool]] = {}
    banner_threshold = max(2, min_columns)

    for row_index, raw_row in enumerate(raw_rows):
        row_cells: list[tuple[str, bool]] = []
        col_index = 0
        is_banner = (
            len(raw_row) == 1
            and raw_row[0].colspan >= banner_threshold
            and raw_row[0].rowspan == 1
        )
        for cell in raw_row:
            while (row_index, col_index) in carried_spans:
                row_cells.append(carried_spans.pop((row_index, col_index)))
                col_index += 1
            value = (cell.text, cell.tag == "th")
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    if dr == 0:
                        row_cells.append(value)
                    else:
                        carried_spans[(row_index + dr, col_index + dc)] = value
            col_index += cell.colspan
        while (row_index, col_index) in carried_spans:
            row_cells.append(carried_spans.pop((row_index, col_index)))
            col_index += 1

        if row_cells:
            grid.append(
                _ParsedGridRow(
                    cells=[text for text, _ in row_cells],
                    all_th=all(is_th for _, is_th in row_cells),
                    is_banner=is_banner,
                )
            )
    return grid


def _clean_cell(text: str, *, strip_leader_dots: bool) -> str:
    collapsed = " ".join(text.split())
    if strip_leader_dots:
        collapsed = _LEADER_DOTS_RE.sub("", collapsed).strip()
    return collapsed


def _is_column_index_row(cells: list[str]) -> bool:
    if len(cells) < 4:
        return False
    return [cell.strip().rstrip(".") for cell in cells[:4]] == ["1", "2", "3", "4"]


def _detect_header_cutoff(rows: list[_ParsedGridRow]) -> int:
    """Return index of the first data row when an HTML table starts with header rows."""
    for idx in range(min(5, len(rows)) - 1, -1, -1):
        if _is_column_index_row(rows[idx].cells):
            return idx + 1
    cutoff = 0
    for idx, row in enumerate(rows[:5]):
        if row.all_th:
            cutoff = idx + 1
        else:
            break
    return cutoff


def _extract_heading_from_text(chunk: str, current: str | None) -> str | None:
    section = current
    for line in chunk.splitlines():
        md_match = _MD_HEADING_RE.match(line)
        if md_match is not None:
            section = md_match.group(1).strip()
            continue
        num_match = _NUMBERED_HEADING_RE.match(line)
        if num_match is not None:
            section = num_match.group(1).strip()
    return section


def _parse_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _split_markdown_segments(
    text: str,
) -> list[tuple[str, str]]:
    """Split text into ('text', str) and ('table', html) segments in order."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _TABLE_BLOCK_RE.finditer(text):
        if match.start() > pos:
            segments.append(("text", text[pos : match.start()]))
        segments.append(("table", match.group(0)))
        pos = match.end()
    if pos < len(text):
        segments.append(("text", text[pos:]))
    return segments


def _derive_inferred_headers(
    header_rows: list[_ParsedGridRow], width: int
) -> list[str]:
    if not header_rows:
        return [f"Column {idx + 1}" for idx in range(width)]
    titles: list[str] = []
    for col_idx in range(width):
        parts: list[str] = []
        for row in header_rows:
            if col_idx < len(row.cells):
                candidate = row.cells[col_idx].strip()
                if (
                    candidate
                    and not _INDEX_CELL_RE.fullmatch(candidate)
                    and candidate not in parts
                ):
                    parts.append(candidate)
        titles.append(" / ".join(parts) if parts else f"Column {col_idx + 1}")
    return titles


class ExtractMarkdownTablesConfig(NodeConfig):
    column_names: list[str] = Field(
        default_factory=list,
        title="Column names",
        description=(
            "Optional explicit column IDs/titles. Leave empty to infer from "
            "the first header row."
        ),
    )
    skip_table_headers: bool = Field(
        default=True,
        title="Skip header rows",
        description="Skip <th> rows, repeated headers, and 1..N column-index rows.",
    )
    include_section_column: bool = Field(
        default=False,
        title="Include section column",
        description=(
            "Record preceding Markdown headings and full-width spanning banner "
            "rows in a 'section' column."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=list,
        title="Required non-empty columns",
        description="Drop rows where any of these column IDs or titles is empty.",
    )
    strip_leader_dots: bool = Field(
        default=True,
        title="Strip leader dots",
        description="Trim trailing dotted leaders like 'м. Бѣлыничи . . . .'.",
    )
    min_columns: int = Field(
        default=2,
        ge=1,
        le=200,
        title="Minimum columns",
    )


class ExtractMarkdownTablesInput(NodeInput):
    markdown: MarkdownValue = Field(title="Markdown document")


class ExtractMarkdownTablesOutput(NodeOutput):
    table: Table = Field(title="Extracted table")


@TABLES.node(
    operator_id="table.extract_from_markdown",
    version=1,
    title="Extract tables from Markdown",
)
@final
class ExtractMarkdownTablesNode(
    Node[
        ExtractMarkdownTablesConfig,
        ExtractMarkdownTablesInput,
        ExtractMarkdownTablesOutput,
    ]
):
    """Extract HTML or Markdown tables from an OCR transcription."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ExtractMarkdownTablesConfig,
        inputs: ExtractMarkdownTablesInput,
        /,
    ) -> ExtractMarkdownTablesOutput:
        markdown = inputs.markdown.markdown
        segments = _split_markdown_segments(markdown)
        has_html_tables = any(kind == "table" for kind, _ in segments)
        table_total = sum(kind == "table" for kind, _ in segments)
        await context.progress("Extracting tables…")
        seen_tables = 0

        current_section: str | None = None
        first_header_rows: list[_ParsedGridRow] = []
        first_header_signature: tuple[str, ...] | None = None
        extracted: list[tuple[str | None, list[str]]] = []

        if has_html_tables:
            for kind, chunk in segments:
                if kind == "text":
                    current_section = _extract_heading_from_text(chunk, current_section)
                    continue
                seen_tables += 1
                if table_total > 1:
                    await context.progress(
                        f"Extracting table {seen_tables} of {table_total}",
                        current=seen_tables,
                        total=table_total,
                    )
                parser = _HtmlTableParser()
                parser.feed(chunk)
                parser.close()
                for raw_table in parser.tables:
                    rows = _expand_html_rows(raw_table, min_columns=config.min_columns)
                    if not rows:
                        continue
                    cutoff = (
                        _detect_header_cutoff(rows) if config.skip_table_headers else 0
                    )
                    if cutoff > 0 and not first_header_rows:
                        first_header_rows = [
                            row
                            for row in rows[:cutoff]
                            if not _is_column_index_row(row.cells)
                        ]
                        if first_header_rows:
                            first_header_signature = tuple(first_header_rows[0].cells)
                    for row in rows[cutoff:]:
                        if row.is_banner:
                            banner_text = row.cells[0].strip() if row.cells else ""
                            if banner_text:
                                current_section = banner_text
                            continue
                        if config.skip_table_headers and (
                            row.all_th
                            or _is_column_index_row(row.cells)
                            or (
                                first_header_signature is not None
                                and tuple(row.cells) == first_header_signature
                            )
                        ):
                            continue
                        if len(row.cells) < config.min_columns:
                            continue
                        extracted.append((current_section, row.cells))
        else:
            lines = markdown.splitlines()
            idx = 0
            while idx < len(lines):
                line = lines[idx]
                if (
                    "|" in line
                    and idx + 1 < len(lines)
                    and _PIPE_SEPARATOR_RE.match(lines[idx + 1]) is not None
                ):
                    header_cells = _parse_pipe_row(line)
                    if not first_header_rows and header_cells:
                        first_header_rows = [
                            _ParsedGridRow(
                                cells=header_cells, all_th=True, is_banner=False
                            )
                        ]
                    if (
                        not config.skip_table_headers
                        and len(header_cells) >= config.min_columns
                    ):
                        extracted.append((current_section, header_cells))
                    idx += 2
                    while idx < len(lines) and "|" in lines[idx] and lines[idx].strip():
                        row_cells = _parse_pipe_row(lines[idx])
                        if len(row_cells) >= config.min_columns:
                            extracted.append((current_section, row_cells))
                        idx += 1
                    continue
                md_match = _MD_HEADING_RE.match(line)
                if md_match is not None:
                    current_section = md_match.group(1).strip()
                else:
                    num_match = _NUMBERED_HEADING_RE.match(line)
                    if num_match is not None:
                        current_section = num_match.group(1).strip()
                idx += 1

        explicit_names = [name.strip() for name in config.column_names if name.strip()]
        if explicit_names:
            if config.include_section_column and "section" in explicit_names:
                raise UserFacingNodeError(
                    "Column name 'section' conflicts with include_section_column"
                )
            data_columns = [
                TableColumn(id=name, title=name, value_type=TableValueType.TEXT)
                for name in explicit_names
            ]
        else:
            max_width = max((len(cells) for _, cells in extracted), default=0)
            inferred_titles = _derive_inferred_headers(first_header_rows, max_width)
            data_columns = [
                TableColumn(
                    id=f"column_{col_idx + 1}",
                    title=inferred_titles[col_idx],
                    value_type=TableValueType.TEXT,
                )
                for col_idx in range(max_width)
            ]

        out_columns = list(data_columns)
        if config.include_section_column:
            out_columns = [
                TableColumn(
                    id="section", title="Section", value_type=TableValueType.TEXT
                ),
                *data_columns,
            ]

        required_ids: list[str] = []
        if config.required_columns:
            by_id = {col.id for col in out_columns}
            by_title: dict[str, list[str]] = {}
            for col in out_columns:
                by_title.setdefault(col.title, []).append(col.id)
            for req in config.required_columns:
                if req in by_id:
                    required_ids.append(req)
                elif len(by_title.get(req, [])) == 1:
                    required_ids.append(by_title[req][0])
                elif len(by_title.get(req, [])) > 1:
                    raise UserFacingNodeError(
                        f"Required column title {req!r} is ambiguous; use a column id"
                    )
                else:
                    raise UserFacingNodeError(
                        f"Required column {req!r} does not exist in extracted columns"
                    )

        out_rows: list[dict[str, TableValue]] = []
        col_count = len(data_columns)
        for section, raw_cells in extracted:
            cleaned = [
                _clean_cell(cell, strip_leader_dots=config.strip_leader_dots)
                for cell in raw_cells
            ]
            out_row: dict[str, TableValue] = {}
            for col_idx, column in enumerate(data_columns):
                value = (
                    cleaned[col_idx]
                    if col_idx < col_count and col_idx < len(cleaned)
                    else ""
                )
                out_row[column.id] = value or None
            if all(val is None for val in out_row.values()):
                continue
            if config.include_section_column:
                out_row["section"] = section
            if any(
                out_row.get(req_id) is None or out_row.get(req_id) == ""
                for req_id in required_ids
            ):
                continue
            out_rows.append(out_row)

        return ExtractMarkdownTablesOutput(
            table=Table(columns=out_columns, rows=out_rows)
        )

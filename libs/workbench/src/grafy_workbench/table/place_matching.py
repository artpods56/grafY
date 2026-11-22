"""Fuzzy place-name matching between reference tables and historical map OCR."""

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Annotated, Literal, final, override

from pydantic import Field, StringConstraints

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import field_ui, when_any, when_field_truthy
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType

from grafy_workbench.table.declaration import TABLES

type ColumnId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]

_HOMOGLYPHS = str.maketrans(
    {
        # Pre-1918 and dialect Cyrillic normalized for comparison.
        "ѣ": "е",
        "і": "и",
        "ї": "и",
        "ё": "е",
        "ѳ": "ф",
        "ѵ": "и",
        "ў": "у",
        "ъ": "",
        "ь": "",
        "й": "и",
        "ы": "и",
        # Latin homoglyphs emitted by Cyrillic OCR on cursive/engraved maps.
        "a": "а",
        "b": "в",
        "c": "с",
        "d": "д",
        "e": "е",
        "f": "ф",
        "g": "г",
        "h": "н",
        "i": "и",
        "j": "и",
        "k": "к",
        "l": "л",
        "m": "м",
        "n": "п",
        "o": "о",
        "p": "р",
        "r": "р",
        "s": "с",
        "t": "т",
        "u": "и",
        "v": "в",
        "w": "ш",
        "x": "х",
        "y": "у",
        "z": "з",
        # Digits frequently confused with Cyrillic glyphs.
        "0": "о",
        "1": "и",
        "3": "з",
        "4": "ч",
        "6": "б",
        "8": "в",
    }
)

_LEADING_TYPE_TOKEN = re.compile(
    r"^(?:г|м|с|д|дер|ус|сл|пос|т|кол|фольв|ф|село|сельцо|местечко|деревня|слобода|город|хутор)\.?\s+",
    re.IGNORECASE,
)
_GLUED_PREFIXES = (
    "местечко",
    "местечно",
    "местеско",
    "месечко",
    "сиесмеко",
    "местек",
    "слобода",
    "деревня",
    "сельцо",
    "город",
    "село",
    "месм",
    "мес",
    "ссм",
    "дер",
    "се",
)
_NON_CYRILLIC = re.compile(r"[^а-я]+")
_SPLIT_TOKENS = re.compile(r"[\s,;:|/\\\-]+")
_SCOPE_SPLIT = re.compile(r"[\s,;|]+")


def normalize_place_tokens(text: str) -> list[str]:
    """Normalize a raw place label into Cyrillic-only tokens with homoglyphs folded."""
    cleaned = _LEADING_TYPE_TOKEN.sub("", unicodedata.normalize("NFC", text).strip())
    translated = cleaned.lower().translate(_HOMOGLYPHS)
    tokens: list[str] = []
    for raw_token in _SPLIT_TOKENS.split(translated):
        token = _NON_CYRILLIC.sub("", raw_token)
        if token:
            tokens.append(token)
    return tokens


def strip_glued_prefix(token: str) -> str:
    """Remove a settlement-type prefix glued onto the start of a place name."""
    for prefix in _GLUED_PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 4:
            return token[len(prefix) :]
    if len(token) >= 6 and token[0] in {"с", "м", "д", "г"}:
        return token[1:]
    return token


def _candidate_forms(text: str) -> list[str]:
    tokens = normalize_place_tokens(text)
    if not tokens:
        return []
    forms: list[str] = []
    joined = "".join(tokens)
    forms.append(joined)
    stripped_joined = strip_glued_prefix(joined)
    if stripped_joined != joined:
        forms.append(stripped_joined)
    for token in tokens:
        if len(token) >= 3 and token not in forms:
            forms.append(token)
        stripped = strip_glued_prefix(token)
        if len(stripped) >= 3 and stripped not in forms:
            forms.append(stripped)
    return forms


def _score_target_against_forms(target: str, forms: list[str]) -> float:
    best = 0.0
    target_len = len(target)
    for form in forms:
        form_len = len(form)
        if form_len < 3:
            continue
        ratio = SequenceMatcher(None, target, form).ratio()
        if form_len < target_len * 0.65:
            ratio *= 0.72
        if ratio > best:
            best = ratio

        # Check sliding windows inside longer glued OCR strings (e.g. prefix + name),
        # including a 1-char shorter tail when OCR truncated the final letter.
        if form_len > target_len and form_len <= target_len + 14:
            for start in range(form_len - target_len + 1):
                window = form[start : start + target_len]
                window_ratio = SequenceMatcher(None, target, window).ratio() * 0.96
                if window_ratio > best:
                    best = window_ratio
        if form_len >= 7:
            for drop in (1, 2):
                tail = form[drop:]
                if len(tail) >= 4:
                    tail_ratio = SequenceMatcher(None, target, tail).ratio() * 0.97
                    if tail_ratio > best:
                        best = tail_ratio
    return best


def score_place_name(reference_text: str, candidate_text: str) -> float:
    """Score similarity in [0, 1] between a reference place name and an OCR reading."""
    ref_tokens = normalize_place_tokens(reference_text)
    target = "".join(ref_tokens)
    if len(target) < 3:
        return 0.0

    forms = _candidate_forms(candidate_text)
    if not forms:
        return 0.0

    return _score_target_against_forms(target, forms)


def _parse_scope_values(value: TableValue) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {part.strip().lower() for part in _SCOPE_SPLIT.split(value) if part.strip()}


def _resolve_column(table: Table, column_ref: str, label: str) -> TableColumn:
    for column in table.columns:
        if column.id == column_ref:
            return column
    title_matches = [column for column in table.columns if column.title == column_ref]
    if len(title_matches) == 1:
        return title_matches[0]
    if len(title_matches) > 1:
        raise UserFacingNodeError(
            f"{label} column title {column_ref!r} is ambiguous; use a column id"
        )
    raise UserFacingNodeError(f"{label} column {column_ref!r} does not exist")


class MatchPlacesConfig(NodeConfig):
    reference_column: ColumnId = Field(
        default="seat_name",
        title="Reference name column ID",
    )
    candidate_column: ColumnId = Field(
        default="name",
        title="Candidate OCR name column ID",
    )
    reference_scope_column: ColumnId | None = Field(
        default=None,
        title="Optional reference scope column ID (e.g. expected sheets)",
        json_schema_extra=field_ui(advanced=True),
    )
    candidate_scope_column: ColumnId | None = Field(
        default=None,
        title="Optional candidate scope column ID (e.g. source_tiff)",
        json_schema_extra=field_ui(advanced=True),
    )
    scope_boost: float = Field(
        default=0.10,
        ge=0.0,
        le=0.5,
        title="Ranking boost when candidate falls in expected scope",
        json_schema_extra=field_ui(
            widget="slider",
            visible_when=when_any(
                when_field_truthy("reference_scope_column"),
                when_field_truthy("candidate_scope_column"),
            ),
        ),
    )
    min_score: float = Field(
        default=0.68,
        ge=0.0,
        le=1.0,
        title="Minimum score for a candidate match",
        json_schema_extra=field_ui(widget="slider"),
    )
    strong_score: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        title="Minimum score for a strong match",
        json_schema_extra=field_ui(widget="slider"),
    )
    candidate_prefix: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ] = Field(
        default="ocr_",
        title="Prefix for joined candidate columns",
        json_schema_extra=field_ui(advanced=True),
    )
    include_unmatched: bool = Field(
        default=True,
        title="Keep unmatched reference rows",
        json_schema_extra=field_ui(advanced=True),
    )
    sort_by: Literal["input", "score_desc"] = Field(
        default="input",
        title="Output row ordering",
        json_schema_extra=field_ui(
            advanced=True,
            enum_labels={"input": "Reference order", "score_desc": "Best match first"},
        ),
    )


class MatchPlacesInput(NodeInput):
    reference: Table = Field(title="Reference place table")
    candidates: Table = Field(title="OCR candidate place table")


class MatchPlacesOutput(NodeOutput):
    matched: Table = Field(title="Matched places table")


_GEO_PASSTHROUGH_COLUMNS = frozenset(
    {"geometry_wkt", "point_wkt", "longitude", "latitude"}
)
_STATUS_ORDER = {"matched": 0, "candidate": 1, "unmatched": 2}


@TABLES.node(
    operator_id="table.match_places",
    version=1,
    title="Match place names (fuzzy Cyrillic)",
)
@final
class MatchPlacesNode(Node[MatchPlacesConfig, MatchPlacesInput, MatchPlacesOutput]):
    """Join a reference place table to noisy historical-map OCR readings."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: MatchPlacesConfig,
        inputs: MatchPlacesInput,
        /,
    ) -> MatchPlacesOutput:
        reference = inputs.reference
        candidates = inputs.candidates

        ref_col = _resolve_column(reference, config.reference_column, "Reference")
        cand_col = _resolve_column(candidates, config.candidate_column, "Candidate")
        ref_scope_col = (
            _resolve_column(reference, config.reference_scope_column, "Reference scope")
            if config.reference_scope_column is not None
            else None
        )
        cand_scope_col = (
            _resolve_column(
                candidates, config.candidate_scope_column, "Candidate scope"
            )
            if config.candidate_scope_column is not None
            else None
        )
        use_scope = ref_scope_col is not None and cand_scope_col is not None

        # Precompute normalized forms for all candidate rows once.
        prepared_candidates: list[
            tuple[dict[str, TableValue], list[str], set[str]]
        ] = []
        for cand_row in candidates.rows:
            raw_name = cand_row[cand_col.id]
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            forms = _candidate_forms(raw_name)
            if not forms:
                continue
            cand_scopes: set[str] = (
                _parse_scope_values(cand_row[cand_scope_col.id])
                if use_scope and cand_scope_col is not None
                else set()
            )
            prepared_candidates.append((cand_row, forms, cand_scopes))

        # Build output column schema without collisions, preferring readable titles
        # when imported CSV columns carry positional ids like "col_1".
        used_ids: set[str] = {
            "match_id",
            "match_status",
            "match_score",
            "in_expected_scope",
        }
        lead_columns: list[TableColumn] = [
            TableColumn(
                id="match_id",
                title="Match ID",
                value_type=TableValueType.INTEGER,
            ),
            TableColumn(
                id="match_status",
                title="Status",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="match_score",
                title="Score",
                value_type=TableValueType.NUMBER,
            ),
        ]
        in_scope_column = TableColumn(
            id="in_expected_scope",
            title="In expected sheet",
            value_type=TableValueType.BOOLEAN,
        )

        ref_col_map: list[tuple[str, str]] = []
        ref_dst_by_src: dict[str, str] = {}
        extra_columns: list[TableColumn] = []
        for col in reference.columns:
            base_name = (
                col.title
                if col.id.startswith(("col_", "column_")) and col.title
                else col.id
            )
            out_id = base_name if base_name not in used_ids else f"ref_{base_name}"
            while out_id in used_ids:
                out_id = f"{out_id}_ref"
            used_ids.add(out_id)
            ref_col_map.append((col.id, out_id))
            ref_dst_by_src[col.id] = out_id
            extra_columns.append(
                TableColumn(id=out_id, title=col.title, value_type=col.value_type)
            )

        cand_col_map: list[tuple[str, str]] = []
        cand_dst_by_src: dict[str, str] = {}
        for col in candidates.columns:
            base_name = (
                col.title
                if col.id.startswith(("col_", "column_")) and col.title
                else col.id
            )
            if base_name in _GEO_PASSTHROUGH_COLUMNS and base_name not in used_ids:
                out_id = base_name
            else:
                out_id = f"{config.candidate_prefix}{base_name}"
                while out_id in used_ids:
                    out_id = f"{out_id}_cand"
            used_ids.add(out_id)
            cand_col_map.append((col.id, out_id))
            cand_dst_by_src[col.id] = out_id
            extra_columns.append(
                TableColumn(id=out_id, title=col.title, value_type=col.value_type)
            )

        columns_by_id = {col.id: col for col in extra_columns}
        columns_by_id[in_scope_column.id] = in_scope_column
        hoist_ids = [ref_dst_by_src[ref_col.id], cand_dst_by_src[cand_col.id]]
        if cand_scope_col is not None:
            hoist_ids.append(cand_dst_by_src[cand_scope_col.id])
        hoist_ids.append(in_scope_column.id)

        seen_col_ids: set[str] = {col.id for col in lead_columns}
        out_columns: list[TableColumn] = list(lead_columns)
        for col_id in hoist_ids:
            if col_id not in seen_col_ids:
                out_columns.append(columns_by_id[col_id])
                seen_col_ids.add(col_id)
        for col in extra_columns:
            if col.id not in seen_col_ids:
                out_columns.append(col)
                seen_col_ids.add(col.id)

        pending_matches: list[
            tuple[
                int,
                str,
                float,
                bool,
                dict[str, TableValue],
                dict[str, TableValue] | None,
            ]
        ] = []
        for idx, ref_row in enumerate(reference.rows):
            raw_ref = ref_row[ref_col.id]
            ref_text = raw_ref if isinstance(raw_ref, str) else ""
            ref_scopes: set[str] = (
                _parse_scope_values(ref_row[ref_scope_col.id])
                if use_scope and ref_scope_col is not None
                else set()
            )

            best_rank = -1.0
            best_score = 0.0
            best_in_scope = False
            best_cand: dict[str, TableValue] | None = None

            target = "".join(normalize_place_tokens(ref_text))
            if len(target) >= 3:
                for cand_row, cand_forms, cand_scopes in prepared_candidates:
                    score = _score_target_against_forms(target, cand_forms)
                    if score <= 0.0:
                        continue
                    in_scope = bool(
                        ref_scopes and cand_scopes and (ref_scopes & cand_scopes)
                    )
                    rank = score + (config.scope_boost if in_scope else 0.0)
                    if rank > best_rank or (rank == best_rank and score > best_score):
                        best_rank = rank
                        best_score = score
                        best_in_scope = in_scope
                        best_cand = cand_row

            if best_cand is not None and best_score >= config.strong_score:
                status = "matched"
            elif best_cand is not None and best_score >= config.min_score:
                status = "candidate"
            else:
                status = "unmatched"

            if status == "unmatched" and not config.include_unmatched:
                continue

            pending_matches.append(
                (idx, status, best_score, best_in_scope, ref_row, best_cand)
            )

        if config.sort_by == "score_desc":
            pending_matches.sort(
                key=lambda item: (_STATUS_ORDER[item[1]], -item[2], item[0])
            )

        out_rows: list[dict[str, TableValue]] = []
        for match_id, (
            _,
            status,
            best_score,
            best_in_scope,
            ref_row,
            best_cand,
        ) in enumerate(pending_matches, start=1):
            row: dict[str, TableValue] = {
                "match_id": match_id,
                "match_status": status,
                "match_score": round(best_score, 3),
                "in_expected_scope": best_in_scope if status != "unmatched" else False,
            }
            for src_id, dst_id in ref_col_map:
                row[dst_id] = ref_row[src_id]
            for src_id, dst_id in cand_col_map:
                if status == "unmatched" or best_cand is None:
                    row[dst_id] = None
                else:
                    row[dst_id] = best_cand[src_id]
            out_rows.append(row)

        return MatchPlacesOutput(matched=Table(columns=out_columns, rows=out_rows))

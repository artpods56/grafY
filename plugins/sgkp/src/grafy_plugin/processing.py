import ast
import csv
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence, Sized
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, TextIO, cast

from grafy_core.artifacts import JsonObject
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType

from grafy_plugin.models import (
    Confidence,
    Decision,
    ReferenceCandidate,
    ReferenceDecision,
    SettlementTypeEvidence,
    SgkpDataset,
    TargetKind,
)


PROMPT_VERSION = "reference_type_repair_litellm_v2_admin_required_for_point"
DEFAULT_LONG_TEXT_THRESHOLD = 120
DECISIONS: frozenset[str] = frozenset(
    {
        "dodaj_typ_miejscowosci",
        "brak_podstaw",
        "nie_miejscowosc",
        "niepewne",
    }
)
CONFIDENCE_LEVELS: frozenset[str] = frozenset({"wysoka", "srednia", "niska"})
ADMIN_TEXT_RE = re.compile(
    r"(?ix)(?<!\w)(?:"
    r"pow(?:[.]|i(?:at\w*|ecie))?|"
    r"gm(?:[.]|in\w*)?|"
    r"gub(?:[.]|ern\w*)?|"
    r"woj(?:[.]|ew[oó]dztw\w*)?|"
    r"obw(?:[.]|[oó]d\w*)?|"
    r"depart(?:[.]|am\w*)?"
    r")(?=\s|[,;:]|$)"
)
STATISTICS_TEXT_RE = re.compile(
    r"(?i)(?<!\w)(?:dm|dym|mk|mieszk\w*|ludn\w*)(?=\s|[.,:])[.,]?"
)
SETTLEMENT_TEXT_RE = re.compile(
    r"(?ix)(?<!\w)(?:"
    r"wś|wieś\w*|folw\w*[.]?|os[.]|osad\w*|mko|mczko|mstko|msto|miast\w*|"
    r"kol[.]|koloni\w*|zaśc\w*[.]?|przys\w*[.]?|chut\w*[.]?|futor\w*|"
    r"słobod\w*|przedmieś\w*|leśnicz\w*|gajów\w*|karczm\w*|młyn\w*|"
    r"cegiel\w*|browar\w*|hut\w*|kopalni\w*|dobra|dominium|mająt\w*|"
    r"posiadłoś\w*|dwór|budy|buda|st[.]\s*(?:p[.]|dr[.]\s*ż[.])|"
    r"stac\w*\s+(?:poczt\w*|kolej\w*)|przystan\w*|przystanek\w*"
    r")(?!\w)"
)
STRUCTURED_SIGNAL_FIELDS = {
    "powiat_ocr",
    "gmina",
    "gubernia",
    "l_mk_statystyka",
    "l_dm_statystyka",
    "ludność_wyznanie",
}
SYSTEM_PROMPT = (
    "Jestes asystentem historyka analizujacym tekst SGKP. "
    "Nie zgadujesz i odpowiadasz wylacznie poprawnym JSON-em."
)


class ModelResponseError(ValueError):
    """Invalid model JSON together with the raw provider output."""

    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


@dataclass(frozen=True, slots=True)
class SelectionResult:
    candidates: tuple[ReferenceCandidate, ...]
    reference_count: int
    skipped_without_text: int
    skipped_without_signal: int


def load_settlement_type_mapping(handle: TextIO) -> dict[str, str]:
    reader = csv.DictReader(handle)
    required = {"typ_model", "typ_punktu_osadniczego"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise ValueError("Settlement-type catalog is missing required columns")
    mapping: dict[str, str] = {}
    for row in reader:
        source = str(row.get("typ_model", "") or "").strip()
        target = str(row.get("typ_punktu_osadniczego", "") or "").strip()
        if source and target:
            mapping[source.casefold()] = target
    return mapping


def load_abbreviations(handle: TextIO) -> tuple[str, dict[str, str]]:
    lines: list[str] = []
    mapping: dict[str, str] = {}
    for raw_line in handle:
        line = raw_line.strip()
        if not line:
            continue
        lines.append(line)
        if "=" not in line:
            continue
        abbreviation, expansion = line.split("=", 1)
        abbreviation = abbreviation.strip()
        expansion = expansion.strip()
        if abbreviation and expansion:
            mapping[abbreviation.casefold()] = expansion
    return "\n".join(lines), mapping


def parse_sgkp_records(content: bytes, *, source_name: str) -> SgkpDataset:
    try:
        parsed: object = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("File is not UTF-8 JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("SGKP JSON must be an array of records")
    records: list[JsonObject] = []
    for index, item in enumerate(cast(list[object], parsed)):
        if not isinstance(item, dict):
            raise ValueError(f"SGKP record {index} is not an object")
        records.append(cast(JsonObject, item))
    if source_name.strip() == "":
        raise ValueError("SGKP source name must not be blank")
    return SgkpDataset(source_name=source_name.strip(), records=records)


def collect_candidates(
    dataset: SgkpDataset,
    *,
    all_references: bool,
    long_text_threshold: int,
) -> SelectionResult:
    if long_text_threshold < 1:
        raise ValueError("long_text_threshold must be positive")
    candidates: list[ReferenceCandidate] = []
    seen_ids: set[str] = set()
    reference_count = 0
    skipped_without_text = 0
    skipped_without_signal = 0

    for record_index, record in enumerate(dataset.records):
        kind = record.get("rodzaj")
        if kind == "indywidualne":
            candidate, skipped = _candidate_from_target(
                record,
                record_index=record_index,
                element_index=None,
                parent=None,
                scoped_text=None,
                seen_ids=seen_ids,
                long_text_threshold=long_text_threshold,
            )
            if skipped == "not_reference":
                continue
            reference_count += 1
            if skipped == "no_text":
                skipped_without_text += 1
                continue
            if candidate is None:
                continue
            if all_references or candidate.candidate_reasons:
                candidates.append(candidate)
            else:
                skipped_without_signal += 1
        elif kind == "zbiorcze":
            elements = record.get("elementy", [])
            if not isinstance(elements, list):
                continue
            for element_index, element in enumerate(cast(list[object], elements)):
                if not isinstance(element, dict):
                    continue
                candidate, skipped = _candidate_from_target(
                    cast(JsonObject, element),
                    record_index=record_index,
                    element_index=element_index,
                    parent=record,
                    scoped_text=text_scoped_to_element(
                        cast(list[object], elements), element_index
                    ),
                    seen_ids=seen_ids,
                    long_text_threshold=long_text_threshold,
                )
                if skipped == "not_reference":
                    continue
                reference_count += 1
                if skipped == "no_text":
                    skipped_without_text += 1
                    continue
                if candidate is None:
                    continue
                if all_references or candidate.candidate_reasons:
                    candidates.append(candidate)
                else:
                    skipped_without_signal += 1

    return SelectionResult(
        candidates=tuple(candidates),
        reference_count=reference_count,
        skipped_without_text=skipped_without_text,
        skipped_without_signal=skipped_without_signal,
    )


def candidates_table(candidates: Sequence[ReferenceCandidate]) -> Table:
    rows: list[dict[str, TableValue]] = [
        {
            "entry_id": candidate.entry_id,
            "name": candidate.name,
            "target_kind": candidate.target_kind,
            "parent_id": candidate.parent_id,
            "types_before": " | ".join(candidate.types_before),
            "settlement_types_before": " | ".join(candidate.settlement_types_before),
            "candidate_reasons": " | ".join(candidate.candidate_reasons),
            "text_length": len(candidate.text),
        }
        for candidate in candidates
    ]
    return Table(
        columns=[
            TableColumn(id="entry_id", title="ID", value_type=TableValueType.TEXT),
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
            TableColumn(
                id="target_kind",
                title="Target kind",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="parent_id",
                title="Parent ID",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="types_before",
                title="Types before",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="settlement_types_before",
                title="Settlement types before",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="candidate_reasons",
                title="Candidate reasons",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="text_length",
                title="Text length",
                value_type=TableValueType.INTEGER,
            ),
        ],
        rows=rows,
    )


def results_table(applied: ApplyResult) -> Table:
    rows: list[dict[str, TableValue]] = [
        {
            "entry_id": row.decision.entry_id,
            "name": row.decision.name,
            "decision": row.decision.decision,
            "confidence": row.decision.confidence,
            "types_before": " | ".join(row.decision.types_before),
            "recognized_types": " | ".join(
                item.type_name for item in row.decision.settlement_types
            ),
            "types_after": " | ".join(row.types_after),
            "has_administrative_location": row.decision.has_administrative_location,
            "administrative_location_evidence": (
                row.decision.administrative_location_evidence
            ),
            "settlement_types_before": " | ".join(
                row.decision.settlement_types_before
            ),
            "recognized_settlement_point_types": " | ".join(
                row.decision.settlement_point_types
            ),
            "settlement_types_after": " | ".join(row.settlement_types_after),
            "evidence": " | ".join(
                item.evidence for item in row.decision.settlement_types
            ),
            "reasoning": row.decision.reasoning,
            "changed": row.changed,
        }
        for row in applied.rows
    ]
    return Table(
        columns=[
            TableColumn(id="entry_id", title="ID", value_type=TableValueType.TEXT),
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
            TableColumn(
                id="decision", title="Decision", value_type=TableValueType.TEXT
            ),
            TableColumn(
                id="confidence",
                title="Confidence",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="types_before",
                title="Types before",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="recognized_types",
                title="Recognized types",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="types_after",
                title="Types after",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="has_administrative_location",
                title="Administrative location",
                value_type=TableValueType.BOOLEAN,
            ),
            TableColumn(
                id="administrative_location_evidence",
                title="Administrative evidence",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="settlement_types_before",
                title="Settlement types before",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="recognized_settlement_point_types",
                title="Recognized settlement points",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="settlement_types_after",
                title="Settlement types after",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="evidence", title="Evidence", value_type=TableValueType.TEXT
            ),
            TableColumn(
                id="reasoning",
                title="Reasoning",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(id="changed", title="Changed", value_type=TableValueType.BOOLEAN),
        ],
        rows=rows,
    )


@dataclass(frozen=True, slots=True)
class AppliedDecisionRow:
    decision: ReferenceDecision
    types_after: tuple[str, ...]
    settlement_types_after: tuple[str, ...]
    changed: bool


@dataclass(frozen=True, slots=True)
class ApplyResult:
    dataset: SgkpDataset
    rows: tuple[AppliedDecisionRow, ...]
    changed_records: int
    changed_types: int
    changed_settlement_types: int


def apply_decisions(
    dataset: SgkpDataset,
    decisions: Sequence[ReferenceDecision],
    *,
    apply_medium_confidence: bool,
) -> ApplyResult:
    records = deepcopy(dataset.records)
    rows: list[AppliedDecisionRow] = []
    changed_records = 0
    changed_types = 0
    changed_settlement_types = 0
    for decision in decisions:
        types_after = tuple(decision.types_before)
        settlement_after = tuple(decision.settlement_types_before)
        changed = False
        if _should_apply(decision, apply_medium_confidence=apply_medium_confidence):
            target = _resolve_target(records, decision)
            current_types = string_list(target.get("typ"), "typ")
            if current_types == list(decision.types_before):
                recognized = [item.type_name for item in decision.settlement_types]
                merged_types = unique_strings([*current_types, *recognized])
                current_points = string_list(
                    target.get("typ_punktu_osadniczego"),
                    "typ_punktu_osadniczego",
                )
                if decision.has_administrative_location:
                    merged_points = unique_strings(
                        [*current_points, *decision.settlement_point_types]
                    )
                else:
                    merged_points = current_points
                type_changed = merged_types != current_types
                point_changed = merged_points != current_points
                if type_changed:
                    target["typ"] = merged_types
                    changed_types += 1
                if point_changed:
                    target["typ_punktu_osadniczego"] = merged_points
                    changed_settlement_types += 1
                if type_changed or point_changed:
                    changed_records += 1
                    changed = True
                types_after = tuple(merged_types)
                settlement_after = tuple(merged_points)
        rows.append(
            AppliedDecisionRow(
                decision=decision,
                types_after=types_after,
                settlement_types_after=settlement_after,
                changed=changed,
            )
        )
    return ApplyResult(
        dataset=SgkpDataset(source_name=dataset.source_name, records=records),
        rows=tuple(rows),
        changed_records=changed_records,
        changed_types=changed_types,
        changed_settlement_types=changed_settlement_types,
    )


def build_prompt(candidate: ReferenceCandidate, abbreviations_text: str) -> str:
    return f"""Ocen rekord SGKP, ktoremu obecnie przypisano typ `odsyłacz`.

ID: {candidate.entry_id}
Nazwa hasla: {candidate.name}
Rodzaj rekordu: {candidate.target_kind}
Obecne typy: {json.dumps(candidate.types_before, ensure_ascii=False)}

TEKST:
{candidate.text}

CEL:
Wykonaj dwie osobne oceny:
A. Ustal, czy haslo poza odeslaniem do innego artykulu jawnie podaje typ
   glownego obiektu, np. wieś, folwark, osada, miasto, miasteczko, kolonia,
   zaścianek, przysiółek, chutor, leśniczówka, młyn albo stacja pocztowa.
B. Niezaleznie ustal, czy TEKST podaje jawne polozenie administracyjne tego
   samego glownego obiektu. Ta druga informacja zdecyduje, czy poza polem
   `typ` wolno uzupelnic takze `typ_punktu_osadniczego`.

REGULY:
1. Typ `odsyłacz` pozostaje w danych. Wskazujesz tylko dodatkowe typy
   miejscowosci, ktore nalezy do niego dopisac.
2. Skrót `ob.` lub `zob.` sam w sobie oznacza odeslanie i nie wyklucza
   dodatkowego typu. Przykład `Aleksandrowo, folw., pow. pleszewski, ob.
   Klenka` jest jednoczesnie odsyłaczem i opisem folwarku.
3. `Anisiniowicze, wś, pow. nowogródzki, 200 mieszk., ob. Dryświaty` wymaga
   typu `wieś`. Dane administracyjne, liczba domow lub mieszkańców wzmacniaja
   pewnosc, ze opis dotyczy rzeczywistej miejscowosci.
4. Sam zapis `Nazwa, ob. InnaNazwa`, lista wariantow nazw albo tlumaczenie
   nazwy bez typu i bez realnego opisu obiektu nie wystarcza. Wybierz wtedy
   `brak_podstaw`.
5. Haslo moze byc rozbudowanym odsyłaczem do rzeki, jeziora, gory, pasma,
   krainy albo innego obiektu nieosadniczego. Wtedy wybierz
   `nie_miejscowosc` i nie zwracaj typu miejscowosci.
6. Typ i dane musza dotyczyc glownego obiektu o nazwie podanej w `Nazwa
   hasla`. Nie przenos typu obiektu wymienionego dopiero po `ob.` ani typu
   sasiedniej lub nadrzednej miejscowosci.
7. Nie wyprowadzaj typu jedynie z powiatu, gminy, parafii lub liczby ludnosci.
   Ogolny typ `miejscowość` wolno zwrocic tylko wtedy, gdy to slowo wystepuje
   jawnie w tekscie. W przeciwnym razie wybierz `brak_podstaw` albo
   `niepewne`.
8. Typy zwracaj jako pelne nazwy, nigdy jako skroty: `wś` -> `wieś`, `folw.`
   -> `folwark`, `mko` -> `miasteczko`, `os.` -> `osada`.
9. Gdy tekst podaje kilka typow glownego obiektu, zwroc je osobno, np.
   `wś i folw.` -> `wieś` oraz `folwark`. Nie lacz ich w jeden napis.
10. Nie zwracaj `odsyłacz` w `typy_miejscowosci`; ten typ juz istnieje.
11. Kazdy `dowod` ma byc krotkim, doslownym cytatem z TEKSTU zawierajacym
    oznaczenie danego typu. Nie parafrazuj i nie cytuj samej nazwy hasla.
12. Wybierz wysoka pewnosc tylko dla typu podanego wprost. Srednia jest
    dopuszczalna dla ogolnego `miejscowość`. Przy sprzecznosci wybierz
    `niepewne`.
13. Rozpoznany typ miejscowosci nalezy dodac do pola `typ` nawet wtedy, gdy
    tekst nie zawiera polozenia administracyjnego.
14. Ustaw `ma_polozenie_administracyjne` na true tylko wtedy, gdy TEKST
    jawnie przypisuje glowny obiekt do jednostki administracyjnej, np.
    `pow. pleszewski`, `w powiecie nowogródzkim`, `gm. Trojanów`,
    `gub. kowieńska`, `województwo krakowskie` albo `obwód białostocki`.
    Dowod musi obejmowac oznaczenie jednostki oraz jej nazwe lub jawne
    `t. n.` oznaczajace jednostke tej samej nazwy.
15. Sama informacja `przys.`, `wś`, `folw.` itp., sama nazwa, odeslanie,
    odleglosc, polozenie nad rzeka, przynaleznosc do parafii albo liczba
    domow i mieszkancow nie jest polozeniem administracyjnym. W takich
    przypadkach ustaw false.
16. Skrot `g.` nie oznacza gminy. Nie uznawaj go za dowod polozenia
    administracyjnego. Zapis o urzedzie lub zarzadzie gminnym bez wskazania,
    do jakiej jednostki nalezy glowny obiekt, rowniez nie wystarcza.
17. Polozenie administracyjne musi dotyczyc glownego obiektu. Nie wolno
    wykorzystac danych miejscowosci wymienionej dopiero po `ob.` ani innego
    obiektu opisanego w tekscie.
18. `dowod_polozenia_administracyjnego` ma byc krotkim, doslownym cytatem z
    TEKSTU. Gdy ustawiasz false, zwroc pusty napis.

SLOWNIK SKROTOW SGKP:
{abbreviations_text}

Dozwolone decyzje: `dodaj_typ_miejscowosci`, `brak_podstaw`,
`nie_miejscowosc`, `niepewne`.
Dozwolona pewnosc: `wysoka`, `srednia`, `niska`.

Zwroc wylacznie obiekt JSON:
{{
  "decyzja": "dodaj_typ_miejscowosci",
  "pewnosc": "wysoka",
  "typy_miejscowosci": [
    {{"typ": "wieś", "dowod": "wś"}},
    {{"typ": "folwark", "dowod": "folw."}}
  ],
  "ma_polozenie_administracyjne": true,
  "dowod_polozenia_administracyjnego": "pow. pleszewski",
  "uzasadnienie": "Tekst jawnie okresla typ glownego obiektu."
}}

Dla decyzji innych niz `dodaj_typ_miejscowosci` zwroc pusta liste
`typy_miejscowosci`, false w `ma_polozenie_administracyjne` i pusty napis w
`dowod_polozenia_administracyjnego`."""


def parse_model_json(output: str) -> dict[str, Any]:
    stripped = output.strip()
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end >= start:
        candidates.append(stripped[start : end + 1])
    for candidate in list(candidates):
        if candidate.startswith("{{") and candidate.endswith("}}"):
            candidates.append(candidate[1:-1])
        if candidate.startswith("{{"):
            candidates.append(candidate[1:])
        if candidate.endswith("}}"):
            candidates.append(candidate[:-1])
    errors: list[str] = []
    for candidate in candidates:
        try:
            parsed_json: object = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if isinstance(parsed_json, dict):
            return cast(dict[str, Any], parsed_json)
        errors.append("element glowny nie jest obiektem")
    for candidate in candidates:
        try:
            parsed_literal: object = ast.literal_eval(candidate)
        except (SyntaxError, ValueError, TypeError) as exc:
            errors.append(str(exc))
            continue
        if isinstance(parsed_literal, dict):
            return cast(dict[str, Any], parsed_literal)
        errors.append("element glowny zapisu tolerancyjnego nie jest obiektem")
    detail = errors[-1] if errors else "brak obiektu"
    raise ModelResponseError(f"Nie mozna odczytac JSON modelu: {detail}", output)


def normalize_response(
    parsed: Mapping[str, Any],
    candidate: ReferenceCandidate,
    *,
    settlement_mapping: Mapping[str, str],
    abbreviations: Mapping[str, str],
    model: str,
) -> ReferenceDecision:
    payload: dict[str, Any] = dict(parsed)
    nested = payload.get("wynik")
    if isinstance(nested, dict):
        payload = dict(cast(Mapping[str, Any], nested))
    decision = str(payload.get("decyzja", "") or "").strip().casefold()
    aliases = {
        "dodaj_typ": "dodaj_typ_miejscowosci",
        "odsyłacz_i_miejscowość": "dodaj_typ_miejscowosci",
        "odsyłacz_i_miejscowosc": "dodaj_typ_miejscowosci",
        "czysty_odsyłacz": "brak_podstaw",
        "brak": "brak_podstaw",
        "nie_dotyczy": "nie_miejscowosc",
        "nie_miejscowość": "nie_miejscowosc",
    }
    decision = aliases.get(decision, decision)
    if decision not in DECISIONS:
        raise ValueError(f"Niepoprawna decyzja: {decision!r}")
    confidence = str(payload.get("pewnosc", "") or "").strip().casefold()
    confidence_aliases = {
        "wysoki": "wysoka",
        "średnia": "srednia",
        "średni": "srednia",
        "sredni": "srednia",
        "niski": "niska",
    }
    confidence = confidence_aliases.get(confidence, confidence)
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"Niepoprawna pewnosc: {confidence!r}")
    reasoning = str(payload.get("uzasadnienie", "") or "").strip()
    has_administrative_location = boolean_field(payload, "ma_polozenie_administracyjne")
    administrative_evidence = str(
        payload.get("dowod_polozenia_administracyjnego", "") or ""
    ).strip()
    raw_types = payload.get("typy_miejscowosci", [])
    if raw_types is None:
        raw_types = []
    if not isinstance(raw_types, list):
        raise ValueError("typy_miejscowosci nie jest lista")

    if decision != "dodaj_typ_miejscowosci":
        if raw_types:
            raise ValueError(
                f"Decyzja {decision} wymaga pustej listy typy_miejscowosci"
            )
        if has_administrative_location or administrative_evidence:
            raise ValueError(
                f"Decyzja {decision} wymaga braku polozenia administracyjnego"
            )
        return _decision(
            candidate,
            decision=cast(Decision, decision),
            confidence=cast(Confidence, confidence),
            settlement_types=(),
            settlement_point_types=(),
            has_administrative_location=False,
            administrative_location_evidence="",
            reasoning=reasoning,
            model=model,
        )

    if not raw_types:
        raise ValueError("Decyzja dodaj_typ_miejscowosci wymaga co najmniej jednego typu")
    normalized_types: list[SettlementTypeEvidence] = []
    seen_types: set[str] = set()
    for item in cast(list[object], raw_types):
        if not isinstance(item, dict):
            raise ValueError("Element typy_miejscowosci nie jest obiektem")
        typed_item = cast(Mapping[str, object], item)
        raw_type = str(typed_item.get("typ", "") or "").strip()
        evidence = str(typed_item.get("dowod", "") or "").strip()
        if not raw_type or not evidence:
            raise ValueError("Brak typu lub dowodu w typy_miejscowosci")
        entry_type = normalize_entry_type(raw_type, abbreviations)
        if entry_type.casefold() == "odsyłacz":
            raise ValueError("Nie wolno zwracac typu odsyłacz jako typu miejscowosci")
        if normalized_text(evidence) not in normalized_text(candidate.text):
            raise ValueError(f"Dowod dla typu {entry_type} nie wystepuje w tekscie")
        if not type_supported_by_evidence(entry_type, evidence, abbreviations):
            raise ValueError(f"Dowod nie potwierdza typu {entry_type}")
        settlement_types, unknown, not_applicable = settlement_types_for(
            [entry_type], settlement_mapping
        )
        if unknown:
            raise ValueError(f"Typ nie wystepuje w katalogu eksperckim: {entry_type}")
        if not_applicable or not settlement_types:
            raise ValueError(f"Typ nie jest typem punktu osadniczego: {entry_type}")
        key = entry_type.casefold()
        if key not in seen_types:
            seen_types.add(key)
            normalized_types.append(
                SettlementTypeEvidence(type_name=entry_type, evidence=evidence)
            )

    settlement_types, _, _ = settlement_types_for(
        [item.type_name for item in normalized_types], settlement_mapping
    )
    if has_administrative_location:
        if not administrative_evidence:
            raise ValueError(
                "Brak dowodu polozenia administracyjnego dla wartosci true"
            )
        if normalized_text(administrative_evidence) not in normalized_text(
            candidate.text
        ):
            raise ValueError(
                "Dowod polozenia administracyjnego nie wystepuje w tekscie"
            )
        if not administrative_evidence_supported(administrative_evidence):
            raise ValueError(
                "Dowod nie zawiera nazwanego polozenia administracyjnego"
            )
    elif administrative_evidence:
        raise ValueError(
            "Dla braku polozenia administracyjnego dowod musi byc pusty"
        )
    return _decision(
        candidate,
        decision="dodaj_typ_miejscowosci",
        confidence=cast(Confidence, confidence),
        settlement_types=tuple(normalized_types),
        settlement_point_types=tuple(
            settlement_types if has_administrative_location else []
        ),
        has_administrative_location=has_administrative_location,
        administrative_location_evidence=administrative_evidence,
        reasoning=reasoning,
        model=model,
    )


def correction_prompt(base_prompt: str, error: Exception, raw_output: str) -> str:
    return (
        f"{base_prompt}\n\nPOPRZEDNIA ODPOWIEDZ BYLA NIEPOPRAWNA. "
        f"Walidator zglosil: {short_error(error)}. "
        "Zwroc caly poprawiony obiekt JSON bez komentarza.\n"
        f"{raw_output}"
    )


def short_error(error: Exception) -> str:
    message = " ".join((str(error).strip() or error.__class__.__name__).split())
    return message if len(message) <= 500 else message[:497] + "..."


def text_scoped_to_element(elements: Sequence[object], element_index: int) -> str:
    current = elements[element_index]
    if not isinstance(current, dict):
        return ""
    current_record = cast(Mapping[str, object], current)
    text = str(current_record.get("text", "") or "").strip()
    cuts: list[int] = []
    for later in elements[element_index + 1 :]:
        if not isinstance(later, dict):
            continue
        later_record = cast(Mapping[str, object], later)
        later_text = str(later_record.get("text", "") or "").strip()
        if len(later_text) < 10:
            continue
        position = text.find(later_text)
        if position > 0:
            cuts.append(position)
    return text[: min(cuts)].rstrip() if cuts else text


def candidate_reasons(target: Mapping[str, object], text: str, threshold: int) -> list[str]:
    reasons: list[str] = []
    if SETTLEMENT_TEXT_RE.search(text):
        reasons.append("sygnal_typu_w_tekscie")
    if ADMIN_TEXT_RE.search(text):
        reasons.append("dane_administracyjne_w_tekscie")
    if STATISTICS_TEXT_RE.search(text):
        reasons.append("statystyka_w_tekscie")
    structured = sorted(
        field for field in STRUCTURED_SIGNAL_FIELDS if has_value(target.get(field))
    )
    if structured:
        reasons.append("istniejace_pola:" + ",".join(structured))
    if len(text) >= threshold:
        reasons.append("dluzszy_opis")
    return reasons


def string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        raise ValueError(f"Pole {field} nie jest lista napisow")
    items = cast(list[object], value)
    if any(not isinstance(item, str) for item in items):
        raise ValueError(f"Pole {field} nie jest lista napisow")
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def unique_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def contains_reference_type(value: object) -> bool:
    try:
        types = string_list(value, "typ")
    except ValueError:
        return False
    return any(item.casefold() == "odsyłacz" for item in types)


def normalize_entry_type(value: str, abbreviations: Mapping[str, str]) -> str:
    cleaned = " ".join(value.split()).strip()
    return " ".join(abbreviations.get(cleaned.casefold(), cleaned).split()).strip()


def settlement_types_for(
    entry_types: Sequence[str],
    mapping: Mapping[str, str],
) -> tuple[list[str], list[str], list[str]]:
    settlement_types: list[str] = []
    unknown: list[str] = []
    not_applicable: list[str] = []
    for entry_type in entry_types:
        mapped = mapping.get(entry_type.casefold())
        if mapped is None:
            unknown.append(entry_type)
        elif mapped.casefold() == "nie dotyczy":
            not_applicable.append(entry_type)
        elif mapped not in settlement_types:
            settlement_types.append(mapped)
    return settlement_types, unknown, not_applicable


def type_supported_by_evidence(
    entry_type: str,
    evidence: str,
    abbreviations: Mapping[str, str],
) -> bool:
    normalized_type = normalized_text(entry_type)
    normalized_evidence = normalized_text(evidence)
    if normalized_type in normalized_evidence:
        return True
    type_words = word_tokens(entry_type)
    evidence_words = word_tokens(evidence)
    if any(
        words_roughly_match(type_word, evidence_word)
        for type_word in type_words
        for evidence_word in evidence_words
    ):
        return True
    for abbreviation, expansion in abbreviations.items():
        if normalized_text(expansion) != normalized_type:
            continue
        if normalized_text(abbreviation) in normalized_evidence:
            return True
    return False


def administrative_evidence_supported(evidence: str) -> bool:
    if not ADMIN_TEXT_RE.search(evidence):
        return False
    normalized = normalized_text(evidence)
    if re.search(r"(?<!\w)t\s*[.]?\s*n\s*[.]?(?!\w)", normalized):
        return True
    remainder = ADMIN_TEXT_RE.sub(" ", normalized)
    ignored = {"w", "we", "z", "ze", "do", "na", "i", "oraz"}
    return any(
        len(token) >= 3 and token not in ignored for token in word_tokens(remainder)
    )


def boolean_field(parsed: Mapping[str, Any], field: str) -> bool:
    value = parsed.get(field)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "tak"}:
            return True
        if normalized in {"false", "nie"}:
            return False
    raise ValueError(f"Pole {field} nie jest wartoscia logiczna")


def has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "/", "null", "none", "brak"}
    if isinstance(value, (list, dict, tuple, set)):
        return len(cast(Sized, value)) > 0
    return True


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("„", '"').replace("”", '"').replace("’", "'")
    return " ".join(value.split())


def word_tokens(value: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", normalized_text(value), flags=re.UNICODE)


def words_roughly_match(left: str, right: str) -> bool:
    if left == right:
        return True
    shortest = min(len(left), len(right))
    if shortest < 4:
        return False
    common = 0
    for left_char, right_char in zip(left, right, strict=False):
        if left_char != right_char:
            break
        common += 1
    return common >= max(4, shortest - 3)


def _candidate_from_target(
    target: JsonObject,
    *,
    record_index: int,
    element_index: int | None,
    parent: JsonObject | None,
    scoped_text: str | None,
    seen_ids: set[str],
    long_text_threshold: int,
) -> tuple[ReferenceCandidate | None, str | None]:
    if not contains_reference_type(target.get("typ")):
        return None, "not_reference"
    text = scoped_text if scoped_text is not None else str(target.get("text", "") or "").strip()
    if not text:
        return None, "no_text"
    record_id = str(target.get("ID", "") or "").strip()
    if not record_id:
        raise ValueError(
            f"SGKP reference is missing ID at record {record_index}, "
            f"element {element_index}"
        )
    if record_id in seen_ids:
        raise ValueError(f"Duplicate SGKP reference ID: {record_id}")
    seen_ids.add(record_id)
    name = target.get("nazwa")
    parent_id = None
    if parent is not None:
        parent_id = str(parent.get("ID", "") or "").strip() or None
    target_kind: TargetKind = "element" if element_index is not None else "indywidualne"
    return (
        ReferenceCandidate(
            entry_id=record_id,
            name=str(name).strip() if isinstance(name, str) and name.strip() else None,
            target_kind=target_kind,
            parent_id=parent_id,
            record_index=record_index,
            element_index=element_index,
            text=text,
            types_before=string_list(target.get("typ"), "typ"),
            settlement_types_before=string_list(
                target.get("typ_punktu_osadniczego"),
                "typ_punktu_osadniczego",
            ),
            candidate_reasons=candidate_reasons(target, text, long_text_threshold),
        ),
        None,
    )


def _should_apply(
    decision: ReferenceDecision, *, apply_medium_confidence: bool
) -> bool:
    if decision.decision != "dodaj_typ_miejscowosci":
        return False
    if decision.confidence == "wysoka":
        return True
    return decision.confidence == "srednia" and apply_medium_confidence


def _resolve_target(
    records: list[JsonObject], decision: ReferenceDecision
) -> JsonObject:
    if decision.record_index >= len(records):
        raise ValueError(f"Decision {decision.entry_id} points outside the dataset")
    record = records[decision.record_index]
    if decision.element_index is None:
        target = record
    else:
        elements = record.get("elementy")
        if not isinstance(elements, list):
            raise ValueError(f"Decision {decision.entry_id} is missing elementy")
        if decision.element_index >= len(cast(list[object], elements)):
            raise ValueError(f"Decision {decision.entry_id} points outside elementy")
        raw_target = cast(list[object], elements)[decision.element_index]
        if not isinstance(raw_target, dict):
            raise ValueError(f"Decision {decision.entry_id} target is not an object")
        target = cast(JsonObject, raw_target)
    if str(target.get("ID", "") or "") != decision.entry_id:
        raise ValueError(f"Dataset structure changed for {decision.entry_id}")
    return target


def _decision(
    candidate: ReferenceCandidate,
    *,
    decision: Decision,
    confidence: Confidence,
    settlement_types: tuple[SettlementTypeEvidence, ...],
    settlement_point_types: tuple[str, ...],
    has_administrative_location: bool,
    administrative_location_evidence: str,
    reasoning: str,
    model: str,
) -> ReferenceDecision:
    return ReferenceDecision(
        entry_id=candidate.entry_id,
        name=candidate.name,
        target_kind=candidate.target_kind,
        parent_id=candidate.parent_id,
        record_index=candidate.record_index,
        element_index=candidate.element_index,
        decision=decision,
        confidence=confidence,
        settlement_types=list(settlement_types),
        settlement_point_types=list(settlement_point_types),
        has_administrative_location=has_administrative_location,
        administrative_location_evidence=administrative_location_evidence,
        reasoning=reasoning,
        types_before=list(candidate.types_before),
        settlement_types_before=list(candidate.settlement_types_before),
        candidate_reasons=list(candidate.candidate_reasons),
        model=model,
        prompt_version=PROMPT_VERSION,
    )

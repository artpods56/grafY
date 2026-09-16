import pytest

from grafy_plugin.dictionaries import bundled_abbreviations, bundled_settlement_mapping
from grafy_plugin.models import ReferenceDecision, SettlementTypeEvidence, SgkpDataset
from grafy_plugin.processing import (
    apply_decisions,
    collect_candidates,
    normalize_response,
    parse_sgkp_records,
)
from sample_dataset import SAMPLE_SGKP_JSON


def sample_dataset() -> SgkpDataset:
    return parse_sgkp_records(SAMPLE_SGKP_JSON, source_name="sgkp_sample.json")


def test_import_rejects_non_array_json() -> None:
    try:
        parse_sgkp_records(b'{"nazwa": "Aa"}', source_name="bad.json")
    except ValueError as exc:
        assert "array" in str(exc)
    else:
        raise AssertionError("expected ValueError")


@pytest.mark.parametrize(
    ("content", "source_name", "message"),
    [
        (b'[{"nazwa": "Aa"}', "sgkp_sample.json", "not UTF-8 JSON"),
        (b"\xff\xfe", "sgkp_sample.json", "not UTF-8 JSON"),
        (b"[1]", "sgkp_sample.json", "record 0 is not an object"),
        (b"[]", "  ", "must not be blank"),
    ],
)
def test_import_rejects_invalid_sgkp_json(
    content: bytes,
    source_name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _ = parse_sgkp_records(content, source_name=source_name)


def test_import_accepts_an_empty_array() -> None:
    dataset = parse_sgkp_records(b"[]", source_name="sgkp_empty.json")
    assert dataset.source_name == "sgkp_empty.json"
    assert dataset.records == []


def test_select_keeps_signaled_references_only() -> None:
    selection = collect_candidates(
        sample_dataset(),
        all_references=False,
        long_text_threshold=120,
    )
    assert selection.reference_count == 3
    assert [candidate.entry_id for candidate in selection.candidates] == [
        "01-00010",
        "01-00100-a",
    ]
    assert selection.skipped_without_signal == 1
    aleksandrowo = selection.candidates[0]
    assert "sygnal_typu_w_tekscie" in aleksandrowo.candidate_reasons
    assert "dane_administracyjne_w_tekscie" in aleksandrowo.candidate_reasons


def test_select_all_references_includes_short_cross_references() -> None:
    selection = collect_candidates(
        sample_dataset(),
        all_references=True,
        long_text_threshold=120,
    )
    assert [candidate.entry_id for candidate in selection.candidates] == [
        "01-00003",
        "01-00010",
        "01-00100-a",
    ]


def test_normalize_adds_settlement_type_when_evidence_is_in_text() -> None:
    selection = collect_candidates(
        sample_dataset(),
        all_references=False,
        long_text_threshold=120,
    )
    candidate = selection.candidates[0]
    _, abbreviations = bundled_abbreviations()
    decision = normalize_response(
        {
            "decyzja": "dodaj_typ_miejscowosci",
            "pewnosc": "wysoka",
            "typy_miejscowosci": [{"typ": "folwark", "dowod": "folw."}],
            "ma_polozenie_administracyjne": True,
            "dowod_polozenia_administracyjnego": "pow. pleszewski",
            "uzasadnienie": "Tekst jawnie okresla typ glownego obiektu.",
        },
        candidate,
        settlement_mapping=bundled_settlement_mapping(),
        abbreviations=abbreviations,
        model="gemma-4-31b-it",
    )
    assert decision.settlement_types == [
        SettlementTypeEvidence(type_name="folwark", evidence="folw.")
    ]
    assert decision.settlement_point_types == ["Folwark"]
    assert decision.has_administrative_location is True


def test_normalize_rejects_evidence_missing_from_text() -> None:
    selection = collect_candidates(
        sample_dataset(),
        all_references=False,
        long_text_threshold=120,
    )
    candidate = selection.candidates[0]
    _, abbreviations = bundled_abbreviations()
    try:
        normalize_response(
            {
                "decyzja": "dodaj_typ_miejscowosci",
                "pewnosc": "wysoka",
                "typy_miejscowosci": [{"typ": "wieś", "dowod": "wś"}],
                "ma_polozenie_administracyjne": False,
                "dowod_polozenia_administracyjnego": "",
                "uzasadnienie": "Zgaduje.",
            },
            candidate,
            settlement_mapping=bundled_settlement_mapping(),
            abbreviations=abbreviations,
            model="gemma-4-31b-it",
        )
    except ValueError as exc:
        assert "nie wystepuje w tekscie" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_apply_writes_high_confidence_types_and_admin_settlement_points() -> None:
    dataset = sample_dataset()
    decision = ReferenceDecision(
        entry_id="01-00010",
        name="Aleksandrowo",
        target_kind="indywidualne",
        parent_id=None,
        record_index=2,
        element_index=None,
        decision="dodaj_typ_miejscowosci",
        confidence="wysoka",
        settlement_types=[
            SettlementTypeEvidence(type_name="folwark", evidence="folw.")
        ],
        settlement_point_types=["Folwark"],
        has_administrative_location=True,
        administrative_location_evidence="pow. pleszewski",
        reasoning="Tekst jawnie okresla typ.",
        types_before=["odsyłacz"],
        settlement_types_before=[],
        candidate_reasons=["sygnal_typu_w_tekscie"],
        model="gemma-4-31b-it",
        prompt_version="test",
    )
    applied = apply_decisions(dataset, [decision], apply_medium_confidence=False)
    record = applied.dataset.records[2]
    assert record["typ"] == ["odsyłacz", "folwark"]
    assert record["typ_punktu_osadniczego"] == ["Folwark"]
    assert applied.changed_records == 1
    assert applied.rows[0].changed is True


def test_apply_skips_medium_confidence_unless_enabled() -> None:
    dataset = sample_dataset()
    decision = ReferenceDecision(
        entry_id="01-00010",
        name="Aleksandrowo",
        target_kind="indywidualne",
        parent_id=None,
        record_index=2,
        element_index=None,
        decision="dodaj_typ_miejscowosci",
        confidence="srednia",
        settlement_types=[
            SettlementTypeEvidence(type_name="folwark", evidence="folw.")
        ],
        settlement_point_types=["Folwark"],
        has_administrative_location=True,
        administrative_location_evidence="pow. pleszewski",
        reasoning="Srednia pewnosc.",
        types_before=["odsyłacz"],
        settlement_types_before=[],
        candidate_reasons=["sygnal_typu_w_tekscie"],
        model="gemma-4-31b-it",
        prompt_version="test",
    )
    skipped = apply_decisions(dataset, [decision], apply_medium_confidence=False)
    assert skipped.dataset.records[2]["typ"] == ["odsyłacz"]
    assert skipped.changed_records == 0
    applied = apply_decisions(dataset, [decision], apply_medium_confidence=True)
    assert applied.dataset.records[2]["typ"] == ["odsyłacz", "folwark"]

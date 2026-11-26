from grafy_api.services.families import build_application_registry
from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.contracts.ocr import CropTextReader, TextBoxDetector
from grafy_plugin_map_toponyms import MAP_TOPONYMS


def test_catalog_keeps_the_map_operators_and_artifact_types() -> None:
    registry = build_application_registry()
    assert MAP_TOPONYMS.slug == "external.map_toponyms"
    assert {
        contract.protocol for contract in MAP_TOPONYMS.service_contract_dependencies
    } == {TextBoxDetector, CropTextReader}
    assert {node.key for node in MAP_TOPONYMS.nodes} == {
        ("ocr.detect_tiff_text", 1),
        ("ocr.recognize_tiff_text", 1),
        ("ocr.prepare_tiff_labels", 1),
        ("ocr.postprocess_tiff_regions", 1),
        ("ocr.filter_tiff_readings", 1),
        ("ocr.places_table", 1),
        ("ocr.collect_map_places", 1),
        ("ocr.georeference_places", 1),
        ("ocr.filter_tiff_jev", 1),
        ("ocr.export_label_studio", 1),
        ("ocr.import_label_studio", 1),
        ("table.match_places", 1),
        ("table.transliterate_cyrillic", 1),
        ("text.transliterate_cyrillic", 1),
    }
    for node in MAP_TOPONYMS.nodes:
        assert registry.node_registration(*node.key).plugin_slug == MAP_TOPONYMS.slug
    for key in ("ocr.tiff_text_regions", "ocr.tiff_recognized_text"):
        assert (
            registry.artifact_type_owner(ArtifactTypeKey(key, 1)) == MAP_TOPONYMS.slug
        )

    transliteration = registry.node_registration("table.transliterate_cyrillic", 1)
    assert set(transliteration.node_class.input_contract.ports) == {"table"}
    assert set(transliteration.node_class.output_contract.ports) == {"table"}

    text = registry.node_registration("text.transliterate_cyrillic", 1)
    assert set(text.node_class.input_contract.ports) == {"text", "recognized"}
    assert set(text.node_class.output_contract.ports) == {"text", "recognized"}
    assert text.node_class.input_contract.ports["text"].exclusive_group == "source"
    assert (
        text.node_class.input_contract.ports["recognized"].exclusive_group == "source"
    )
    assert text.node_class.output_contract.ports["text"].required
    assert text.node_class.output_contract.ports["text"].requires_input is None
    assert (
        text.node_class.output_contract.ports["recognized"].requires_input
        == "recognized"
    )

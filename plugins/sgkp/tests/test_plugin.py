from grafy_core.file_contracts import JSON_FILE
from grafy_core.nodes import PortShape
from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin import PLUGIN


def test_sgkp_plugin_contract_freezes() -> None:
    registry = PluginRegistry()
    registry.install(PLUGIN)
    registry.freeze()

    assert isinstance(PLUGIN, Plugin)
    assert PLUGIN.slug == "sgkp"
    keys = {registration.key for registration in PLUGIN.nodes}
    assert keys == {
        ("sgkp.dataset.import_json", 1),
        ("sgkp.references.select", 1),
        ("sgkp.references.classify", 1),
        ("sgkp.references.apply", 1),
    }
    assert ("sgkp.json.import", 1) not in keys
    assert all(not registration.staged_upload_inputs for registration in PLUGIN.nodes)
    assert {
        (artifact.key.id, artifact.key.schema_version)
        for artifact in PLUGIN.artifact_types
    } == {
        ("sgkp.dataset", 1),
        ("sgkp.reference.candidate", 1),
        ("sgkp.reference.decision", 1),
    }


def test_import_json_takes_one_required_file_json_origin() -> None:
    registration = next(
        registration
        for registration in PLUGIN.nodes
        if registration.key == ("sgkp.dataset.import_json", 1)
    )
    port = registration.node_class.input_contract.ports["file"]
    assert port.shape is PortShape.ONE
    assert port.accepts == JSON_FILE.key
    assert port.also_accepts == ()
    assert port.required

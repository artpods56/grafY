from typing import Any

import pytest
from pydantic import ValidationError

from grafy_core.domain.implementation import (
    BuiltinImplementationIdentity,
    PluginImplementationIdentity,
)
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SAVED_GRAPH_SCHEMA_VERSION,
    SavedGraphDocument,
    SavedGraphNode,
    SavedGraphPluginReleasePin,
)


PIN = SavedGraphPluginReleasePin(
    scope=PluginReleaseScope.SYSTEM,
    slug="external.llm",
    revision=3,
)


def _node(**overrides: Any) -> SavedGraphNode:
    payload: dict[str, Any] = {
        "kind": "builtin",
        "id": "n1",
        "operator_id": "test.arithmetic.add",
        "operator_version": 1,
        "config": {},
        "position": GraphPoint(x=0.0, y=0.0),
    }
    payload.update(overrides)
    return SavedGraphNode.model_validate(payload)


def test_builtin_plugin_and_module_nodes_round_trip() -> None:
    builtin = _node()
    module = _node(
        id="n3",
        kind="module",
        operator_id="graph.module.abc",
        operator_version=2,
    )

    payload = SavedGraphDocument(nodes=(builtin, module)).model_dump(mode="json")
    legacy_plugin = dict(payload["nodes"][0])
    legacy_plugin.update(
        id="n2",
        kind="plugin",
        operator_id="llm.openai_compatible.chat_completion",
        plugin_release_pin=PIN.model_dump(mode="json"),
        config={"model": "example"},
    )
    payload["nodes"].insert(1, legacy_plugin)
    restored = SavedGraphDocument.model_validate(payload)
    assert restored.schema_version == SAVED_GRAPH_SCHEMA_VERSION
    assert restored.nodes[0].kind == "builtin"
    assert restored.nodes[1].kind == "builtin"
    assert restored.nodes[1].operator_id == "llm.openai_compatible.chat_completion"
    assert restored.nodes[1].config_dict() == {"model": "example"}
    assert "plugin_release_pin" not in restored.model_dump(mode="json")["nodes"][1]
    assert restored.nodes[2].kind == "module"
    assert (
        SavedGraphDocument.model_validate(restored.model_dump(mode="json")) == restored
    )


def test_builtin_node_discards_legacy_release_pin() -> None:
    node = _node(plugin_release_pin=PIN)
    assert node.kind == "builtin"
    assert "plugin_release_pin" not in node.model_dump(mode="json")


@pytest.mark.parametrize("pin", [None, {"revision": "invalid"}])
def test_legacy_plugin_node_does_not_require_a_valid_release_pin(pin: object) -> None:
    node = _node(kind="plugin", plugin_release_pin=pin)
    assert node.kind == "builtin"
    assert node.operator_id == "test.arithmetic.add"
    assert "plugin_release_pin" not in node.model_dump(mode="json")


def test_legacy_normalization_still_rejects_invalid_node_fields() -> None:
    with pytest.raises(ValidationError, match="operator_version"):
        _node(kind="plugin", plugin_release_pin=PIN, operator_version=0)
    with pytest.raises(ValidationError, match="kind"):
        _node(kind="unknown", plugin_release_pin=PIN)


def test_saved_graph_document_rejects_legacy_schema_versions() -> None:
    payload = SavedGraphDocument(nodes=(_node(),)).model_dump(mode="json")
    for version in (1, 2, 3, 4, 5):
        payload["schema_version"] = version
        with pytest.raises(ValidationError, match="is not supported"):
            SavedGraphDocument.model_validate(payload)


def test_implementation_identity_separates_builtin_build_from_plugin_release() -> None:
    builtin = BuiltinImplementationIdentity(build_digest="a" * 64)
    plugin = PluginImplementationIdentity(
        plugin_release_pin=PIN,
        manifest_digest="b" * 64,
        image_digest="c" * 64,
    )
    assert builtin.fingerprint_document()["kind"] == "builtin"
    assert plugin.fingerprint_document()["plugin_release_pin"]["revision"] == 3
    assert builtin.fingerprint_document() != plugin.fingerprint_document()

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
        "operator_id": "arithmetic.add",
        "operator_version": 1,
        "config": {},
        "position": GraphPoint(x=0.0, y=0.0),
    }
    payload.update(overrides)
    return SavedGraphNode.model_validate(payload)


def test_builtin_plugin_and_module_nodes_round_trip() -> None:
    builtin = _node()
    plugin = _node(
        id="n2",
        kind="plugin",
        operator_id="llm.openai_compatible.chat_completion",
        plugin_release_pin=PIN,
    )
    module = _node(
        id="n3",
        kind="module",
        operator_id="graph.module.abc",
        operator_version=2,
    )

    document = SavedGraphDocument(nodes=(builtin, plugin, module))
    restored = SavedGraphDocument.model_validate(document.model_dump(mode="json"))
    assert restored.schema_version == SAVED_GRAPH_SCHEMA_VERSION
    assert restored.nodes[0].kind == "builtin"
    assert restored.nodes[1].plugin_release_pin == PIN
    assert restored.nodes[2].kind == "module"


def test_builtin_node_rejects_a_plugin_release_pin() -> None:
    with pytest.raises(ValidationError, match="cannot carry a Plugin release pin"):
        _node(plugin_release_pin=PIN)


def test_plugin_node_requires_an_exact_release_pin() -> None:
    with pytest.raises(ValidationError, match="must pin an exact Plugin release"):
        _node(kind="plugin", operator_id="llm.openai_compatible.chat_completion")


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

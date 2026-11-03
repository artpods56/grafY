import pytest
from pydantic import ValidationError

from grafy_core.domain.implementation import (
    BuiltinImplementationIdentity,
)
from grafy_core.domain.saved_graphs import (
    SAVED_GRAPH_SCHEMA_VERSION,
    GraphDocument,
    GraphNode,
)


def _node_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "builtin",
        "id": "n1",
        "operator_id": "test.arithmetic.add",
        "operator_version": 1,
        "config": {},
        "position": {"x": 0.0, "y": 0.0},
    }
    payload.update(overrides)
    return payload


def _node(**overrides: object) -> GraphNode:
    return GraphNode.model_validate(_node_payload(**overrides))


def test_builtin_and_module_nodes_round_trip() -> None:
    builtin = _node()
    module = _node(
        id="n3",
        kind="module",
        operator_id="graph.module.abc",
        operator_version=2,
    )

    document = GraphDocument(nodes=(builtin, module))
    payload = document.model_dump(mode="json")
    assert GraphDocument.model_validate(payload) == document
    assert payload["schema_version"] == SAVED_GRAPH_SCHEMA_VERSION
    assert [node["kind"] for node in payload["nodes"]] == ["builtin", "module"]


def test_plugin_node_kind_is_rejected() -> None:
    with pytest.raises(ValidationError, match="kind"):
        _node(
            kind="plugin",
            operator_id="llm.openai_compatible.chat_completion",
        )


@pytest.mark.parametrize(
    "pin",
    [
        {"scope": "system", "slug": "external.llm", "revision": 3},
        None,
    ],
)
def test_release_pin_key_is_rejected(pin: object) -> None:
    with pytest.raises(ValidationError, match="plugin_release_pin"):
        _node(plugin_release_pin=pin)


def test_invalid_node_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="operator_version"):
        _node(operator_version=0)
    with pytest.raises(ValidationError, match="kind"):
        _node(kind="unknown")


def test_saved_graph_document_rejects_other_schema_versions() -> None:
    payload = GraphDocument(nodes=(_node(),)).model_dump(mode="json")
    for version in (1, 2, 3, 4, 5, 6):
        payload["schema_version"] = version
        with pytest.raises(ValidationError, match="schema_version"):
            GraphDocument.model_validate(payload)


def test_implementation_identity_is_the_build_digest() -> None:
    builtin = BuiltinImplementationIdentity(build_digest="a" * 64)
    assert builtin.fingerprint_document() == {
        "kind": "builtin",
        "build_digest": "a" * 64,
    }
    assert builtin.provenance_document() == builtin.fingerprint_document()
    with pytest.raises(ValidationError, match="Extra inputs"):
        BuiltinImplementationIdentity.model_validate(
            {
                "kind": "plugin",
                "build_digest": "a" * 64,
                "plugin_release_pin": {
                    "scope": "system",
                    "slug": "external.llm",
                    "revision": 3,
                },
            }
        )

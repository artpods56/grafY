from hashlib import sha256

import pytest

from grafy_core.artifacts import JsonObject
from grafy_core.nodes import (
    NodeContractResolutionError,
    PortShape,
    resolve_node_contracts,
)
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_plugin_python.code import (
    CodeError,
    Context,
    inspect_code,
    load_code,
    payload_classes_source,
)
from grafy_plugin_python.declaration import PORT_ARTIFACT_TYPES
from grafy_plugin_python.nodes import PORT_TYPES, PythonTransformNode
from grafy_plugin_python.plugin import PYTHON
from grafy_workbench.presets import PYTHON_PRESETS, NodePreset
from grafy_workbench.text.plugin import TEXT


@pytest.mark.parametrize("preset", PYTHON_PRESETS, ids=lambda preset: preset.id)
def test_preset_contract_is_derived_from_its_copied_code(preset: NodePreset) -> None:
    report = inspect_code(preset.code, PORT_TYPES)
    assert not report.diagnostics
    assert report.contract is not None
    assert report.contract.model_dump(mode="json") == preset.contract.model_dump(
        mode="json"
    )
    config = preset.node_config()
    assert config["code_sha256"] == sha256(preset.code.encode()).hexdigest()
    assert config["preset_id"] == preset.id


@pytest.mark.parametrize(
    "code,line,message",
    [
        (
            "def transform(text: dict) -> str:\n    return str(text)\n",
            1,
            "not an artifact type",
        ),
        (
            "class Params(BaseModel):\n    unsupported: dict[str, str]\ndef transform(text: str, params: Params) -> str:\n    return text\n",
            2,
            "Params field `unsupported`",
        ),
        ("def transform(text: str) -> str:\n  return (\n", 2, "SyntaxError"),
        ("def transform() -> str:\n    return ''\n", 1, "exactly one data input"),
    ],
)
def test_apply_errors_identify_the_editor_line(
    code: str, line: int, message: str
) -> None:
    report = inspect_code(code, PORT_TYPES)
    assert report.contract is None
    assert report.diagnostics[0].line == line
    assert message in report.diagnostics[0].message


def test_params_form_types_and_context_are_supported() -> None:
    code = """class Params(BaseModel):
    text: str = "default"
    number: int = 2
    fraction: float = 1.5
    enabled: bool = True
    choice: Literal["a", "b"] = "a"
    items: list[str] = Field(default_factory=list)
    optional: str | None = None

def transform(text: str, params: Params, context: Context) -> str:
    return text + params.text
"""
    loaded = load_code(code, PORT_TYPES)
    assert loaded.run({"value": "input"}, {}, Context(workspace_id="workspace")) == {
        "value": "inputdefault"
    }
    with pytest.raises(ValueError):
        Context(workspace_id="workspace").workspace_id = "changed"


def test_wrong_output_type_is_rejected_before_persistence() -> None:
    loaded = load_code("def transform(text: str) -> str:\n    return 123\n", PORT_TYPES)
    with pytest.raises(CodeError, match="wrong type"):
        _ = loaded.run({"value": "input"}, {}, Context(workspace_id="workspace"))


def test_structured_payloads_use_real_generated_annotations() -> None:
    source, _ = payload_classes_source(
        [
            spec
            for spec in PORT_ARTIFACT_TYPES
            if spec.key.id in {"table.data", "text.markdown"}
        ]
    )
    assert "from __future__" not in source
    loaded = load_code(
        "def transform(table: Table) -> Table:\n    return table\n", PORT_TYPES
    )
    payload: JsonObject = {
        "columns": [{"id": "value", "title": "Value", "value_type": "json"}],
        "rows": [{"value": [1, {"nested": True}, None]}],
    }
    assert loaded.run(payload, {}, Context(workspace_id="workspace")) == payload


def test_instance_shapes_resolve_and_invalid_shapes_fail() -> None:
    preset = next(preset for preset in PYTHON_PRESETS if preset.id == "split-text")
    node = PythonTransformNode(InMemoryUnitOfWork())
    bindings = {
        "input": preset.contract.input.artifact_type.key(),
        "output": preset.contract.output.artifact_type.key(),
    }
    resolved = resolve_node_contracts(node, bindings, preset.node_config())
    assert resolved.input_contract.ports["input"].shape is PortShape.ONE
    assert resolved.output_contract.ports["output"].shape is PortShape.MANY
    with pytest.raises(NodeContractResolutionError, match="must be 'one' or 'many'"):
        _ = resolve_node_contracts(
            node, bindings, {**preset.node_config(), "output_shape": "invalid"}
        )


def test_python_is_exact_and_old_text_operators_remain_registered_but_hidden() -> None:
    transform = next(
        node for node in PYTHON.nodes if node.key == ("python.transform", 1)
    )
    assert transform.cache_policy is NodeCachePolicy.EXACT
    old = {
        node.node_class.operator_id: node
        for node in TEXT.nodes
        if node.node_class.operator_id
        in {"text.split", "text.replace", "text.join", "text.as_markdown"}
    }
    assert len(old) == 4
    assert all(not node.listed for node in old.values())

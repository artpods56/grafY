"""Python node presets: ready filled Python nodes under familiar titles.

A preset is data, not an operator. Inserting one copies its code and applied
contract into a new ``python.transform@1`` node of the selected
``external.python`` release, so changing a preset never changes existing nodes.
Each file in this package is one preset.
"""

import tomllib
from hashlib import sha256
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.nodes import PortShape


PYTHON_PLUGIN_SLUG = "external.python"
PYTHON_TRANSFORM_OPERATOR_ID = "python.transform"
PYTHON_TRANSFORM_OPERATOR_VERSION = 1


class _PresetValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PresetArtifactType(_PresetValue):
    id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)

    def key(self) -> ArtifactTypeKey:
        return ArtifactTypeKey(self.id, self.schema_version)


class PresetPort(_PresetValue):
    artifact_type: PresetArtifactType
    shape: PortShape


class PresetContract(_PresetValue):
    """What Apply derives from the preset code, stored so insertion needs no sandbox."""

    input_name: str = Field(min_length=1)
    input: PresetPort
    output: PresetPort
    params_schema: dict[str, JsonValue] | None = None


class NodePreset(_PresetValue):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=100)
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=4_000)
    code: str = Field(min_length=1)
    contract: PresetContract

    def params(self) -> dict[str, JsonValue]:
        """Defaults of the params schema; required fields stay for the user."""

        schema = self.contract.params_schema or {}
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        return {
            name: property_schema["default"]
            for name, property_schema in properties.items()
            if isinstance(property_schema, dict) and "default" in property_schema
        }

    def node_config(self) -> dict[str, JsonValue]:
        """The configuration of a new Python node in its applied state."""

        return {
            "code": self.code,
            "code_sha256": sha256(self.code.encode("utf-8")).hexdigest(),
            "input_shape": self.contract.input.shape.value,
            "output_shape": self.contract.output.shape.value,
            "params_schema": self.contract.params_schema,
            "params": self.params(),
            "preset_id": self.id,
            "preset_version": self.version,
        }


def load_python_presets() -> tuple[NodePreset, ...]:
    presets = tuple(
        NodePreset.model_validate(tomllib.loads(entry.read_text(encoding="utf-8")))
        for entry in sorted(files(__name__).iterdir(), key=lambda entry: entry.name)
        if entry.name.endswith(".toml")
    )
    identities = [preset.id for preset in presets]
    if len(identities) != len(set(identities)):
        raise ValueError("Python preset ids must be unique")
    return presets


PYTHON_PRESETS = load_python_presets()


__all__ = [
    "PYTHON_PLUGIN_SLUG",
    "PYTHON_PRESETS",
    "PYTHON_TRANSFORM_OPERATOR_ID",
    "PYTHON_TRANSFORM_OPERATOR_VERSION",
    "NodePreset",
    "PresetArtifactType",
    "PresetContract",
    "PresetPort",
    "load_python_presets",
]

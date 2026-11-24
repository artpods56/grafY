from collections.abc import Mapping
from typing import Annotated, Any, override

import pytest
from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactTypeKey,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import (
    MAX_NODE_ERROR_MESSAGE_LENGTH,
    ArtifactTypeVariable,
    Binds,
    InputContract,
    InputPortSpec,
    Node,
    NodeContractError,
    NodeContractResolutionError,
    NodeExecutionContext,
    OutputContract,
    OutputPortSpec,
    Plugs,
    PortShape,
    Ref,
    RefSequence,
    UserFacingNodeError,
    derive_input_contract,
    resolve_node_contracts,
)
from grafy_core.declared_values import note_declaration
from pydantic import Field, ValidationError


class ExampleImage:
    pass


class ExampleText:
    pass


note_declaration(ExampleImage, RASTER_IMAGE.key)
note_declaration(ExampleText, TEXT_VALUE.key)


class ExampleConfig(NodeConfig):
    language: str = "eng"


class ExampleInput(NodeInput):
    pages: Annotated[
        list[ExampleImage],
        Field(title="Source pages", description="Images to process in order."),
    ]


class ExampleOutput(NodeOutput):
    pages: list[ExampleImage]


class ExampleNode(Node[ExampleConfig, ExampleInput, ExampleOutput]):
    operator_id = "example.node"
    operator_version = 1

    async def run(
        self,
        _context: NodeExecutionContext,
        _config: ExampleConfig,
        inputs: ExampleInput,
        /,
    ) -> ExampleOutput:
        del inputs
        raise NotImplementedError


class AnnotationShapesInput(NodeInput):
    optional_page: ExampleImage | None = None
    page_batches: Annotated[
        list[list[ExampleImage]],
        Plugs(variadic=True),
    ]
    page_refs: RefSequence[ExampleImage]


class InstancePlugInput(NodeInput):
    items: Annotated[
        list[Ref[ExampleImage] | RefSequence[ExampleImage]],
        Plugs(variadic=True, instance=True),
    ]


class MultiTypeInput(NodeInput):
    source: ExampleImage | ExampleText


class MultiTypeInstancePlugInput(NodeInput):
    items: Annotated[
        list[
            Ref[ExampleText]
            | Ref[ExampleImage]
            | RefSequence[ExampleText]
            | RefSequence[ExampleImage]
        ],
        Plugs(variadic=True, instance=True),
    ]


class UnpairedInstancePlugInput(NodeInput):
    items: Annotated[
        list[Ref[ExampleImage] | RefSequence[ExampleText]],
        Plugs(variadic=True, instance=True),
    ]


class NonVariadicInstancePlugInput(NodeInput):
    items: Annotated[
        list[Ref[ExampleImage] | RefSequence[ExampleImage]],
        Plugs(instance=True),
    ]


class BroadInstancePlugInput(NodeInput):
    items: Annotated[
        list[ArtifactRef | object],
        Plugs(variadic=True, instance=True),
    ]


class ConcreteBindsInput(NodeInput):
    page: Annotated[Ref[ExampleImage], Binds("T")]


class GenericWithoutBindsInput(NodeInput):
    page: Ref[Any]


GENERIC_ARTIFACT = ArtifactTypeVariable("T")


class GenericInput(NodeInput):
    items: Annotated[
        list[Ref[Any] | RefSequence[Any]],
        Plugs(variadic=True, instance=True),
        Binds("T"),
    ]


class GenericOutput(NodeOutput):
    items: Annotated[RefSequence[Any], Binds("T")]


class GenericNode(Node[NoConfig, GenericInput, GenericOutput]):
    operator_id = "example.generic"
    operator_version = 1

    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        inputs: GenericInput,
        /,
    ) -> GenericOutput:
        del inputs
        raise NotImplementedError


class ClaimedFormatNode(GenericNode):
    operator_id = "example.claimed_format"

    @classmethod
    @override
    def validate_artifact_type_bindings(
        cls,
        bindings: Mapping[str, ArtifactTypeKey],
    ) -> None:
        key = bindings.get("T")
        if key is not None and key.id == "file.blob":
            raise NodeContractResolutionError(
                f"Node {cls.operator_id!r} cannot bind {key.id}@"
                f"{key.schema_version} as T"
            )


def test_node_contracts_derive_shape_and_resolver_target_from_annotations() -> None:
    assert ExampleNode.config_contract.model is ExampleConfig
    assert ExampleNode.input_contract.model is ExampleInput
    assert ExampleNode.input_contract.ports["pages"].shape == "many"
    assert ExampleNode.input_contract.ports["pages"].accepted_shapes == (
        PortShape.MANY,
    )
    assert ExampleNode.input_contract.ports["pages"].value_types == (ExampleImage,)
    assert ExampleNode.input_contract.ports["pages"].title == "Source pages"
    assert (
        ExampleNode.input_contract.ports["pages"].description
        == "Images to process in order."
    )
    assert ExampleNode.output_contract.model is ExampleOutput
    assert ExampleNode.output_contract.ports["pages"].shape == "many"


def test_node_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NoConfig.model_validate({"unexpected": True})


def test_user_facing_node_error_requires_a_bounded_nonblank_message() -> None:
    assert str(UserFacingNodeError("  Safe provider failure.  ")) == (
        "Safe provider failure."
    )

    with pytest.raises(ValueError, match="must not be blank"):
        UserFacingNodeError("  ")
    with pytest.raises(ValueError, match="must be at most"):
        UserFacingNodeError("x" * (MAX_NODE_ERROR_MESSAGE_LENGTH + 1))


def test_input_contract_supports_optional_variadic_and_structural_types() -> None:
    contract = derive_input_contract(AnnotationShapesInput)

    optional_page = contract.ports["optional_page"]
    assert optional_page.shape is PortShape.ONE
    assert optional_page.value_types == (ExampleImage,)
    assert optional_page.allows_none is True

    page_batches = contract.ports["page_batches"]
    assert page_batches.shape is PortShape.MANY
    assert page_batches.variadic is True
    assert page_batches.value_types == (ExampleImage,)

    page_refs = contract.ports["page_refs"]
    assert page_refs.shape is PortShape.MANY
    assert page_refs.value_types == ()
    assert page_refs.preserves_ref_container is True


def test_input_contract_derives_ordered_accepted_artifact_types() -> None:
    port = derive_input_contract(MultiTypeInput).ports["source"]

    assert port.accepts == RASTER_IMAGE.key
    assert port.also_accepts == (TEXT_VALUE.key,)
    assert port.accepted_types == (RASTER_IMAGE.key, TEXT_VALUE.key)


def test_single_type_input_port_keeps_its_previous_contract() -> None:
    port = derive_input_contract(AnnotationShapesInput).ports["page_refs"]

    assert port.accepts == RASTER_IMAGE.key
    assert port.also_accepts == ()
    assert port.accepted_types == (RASTER_IMAGE.key,)


def test_input_port_rejects_a_type_variable_with_additional_accepted_types() -> None:
    with pytest.raises(
        NodeContractError,
        match="either an artifact type variable or additional accepted artifact types",
    ):
        InputPortSpec(
            name="source",
            accepts=ArtifactTypeVariable("T"),
            also_accepts=(TEXT_VALUE.key,),
        )


def test_input_port_rejects_repeating_its_primary_artifact_type() -> None:
    with pytest.raises(NodeContractError, match="repeats its primary artifact type"):
        InputPortSpec(
            name="source",
            accepts=RASTER_IMAGE.key,
            also_accepts=(RASTER_IMAGE.key,),
        )


def test_input_port_rejects_duplicate_additional_accepted_types() -> None:
    with pytest.raises(
        NodeContractError,
        match="duplicate additional accepted artifact types",
    ):
        InputPortSpec(
            name="source",
            accepts=RASTER_IMAGE.key,
            also_accepts=(TEXT_VALUE.key, TEXT_VALUE.key),
        )


def test_input_contract_derives_mixed_instance_plug_shapes() -> None:
    items = derive_input_contract(InstancePlugInput).ports["items"]

    assert items.shape is PortShape.ONE
    assert items.accepted_shapes == (PortShape.ONE, PortShape.MANY)
    assert items.variadic is True
    assert items.instance_plugs is True
    assert items.value_types == ()
    assert items.preserves_ref_container is True


def test_input_contract_derives_multi_type_instance_plugs_once_per_type() -> None:
    items = derive_input_contract(MultiTypeInstancePlugInput).ports["items"]

    assert items.shape is PortShape.ONE
    assert items.accepted_shapes == (PortShape.ONE, PortShape.MANY)
    assert items.accepts == TEXT_VALUE.key
    assert items.also_accepts == (RASTER_IMAGE.key,)
    assert items.instance_plugs is True


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (
            UnpairedInstancePlugInput,
            r"UnpairedInstancePlugInput.items must pair each Ref\[T\] with RefSequence",
        ),
        (
            NonVariadicInstancePlugInput,
            "NonVariadicInstancePlugInput.items.*Plugs instance requires variadic plugs",
        ),
        (
            BroadInstancePlugInput,
            "BroadInstancePlugInput.items.*must use Ref, not ArtifactRef",
        ),
    ],
)
def test_input_contract_rejects_invalid_instance_plug_declarations(
    model: type[NodeInput],
    message: str,
) -> None:
    with pytest.raises(NodeContractError, match=message):
        derive_input_contract(model)


def test_spare_plugs_belong_to_instance_plugs_only() -> None:
    with pytest.raises(NodeContractError, match="Plugs spare requires instance plugs"):
        Plugs(variadic=True, spare=True)

    spare = Plugs(variadic=True, instance=True, spare=True)
    assert spare.spare is True


def test_binds_is_only_for_a_generic_ref() -> None:
    with pytest.raises(NodeContractError, match="concrete port cannot declare Binds"):
        derive_input_contract(ConcreteBindsInput)
    with pytest.raises(NodeContractError, match="generic port requires Binds"):
        derive_input_contract(GenericWithoutBindsInput)


def test_generic_node_contract_resolves_shared_variable_without_mutation() -> None:
    node = GenericNode()
    artifact_type = ArtifactTypeKey("example.value", 2)
    input_port = node.input_contract.ports["items"]
    output_port = node.output_contract.ports["items"]

    resolved = resolve_node_contracts(node, {"T": artifact_type})

    assert node.input_contract.ports["items"] is input_port
    assert node.output_contract.ports["items"] is output_port
    assert input_port.accepts == GENERIC_ARTIFACT
    assert output_port.produces == GENERIC_ARTIFACT
    assert resolved.input_contract.ports["items"].accepts == artifact_type
    assert resolved.output_contract.ports["items"].produces == artifact_type


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        ({}, "missing artifact type bindings: T"),
        (
            {
                "T": ArtifactTypeKey("example.value", 1),
                "Unknown": ArtifactTypeKey("example.value", 1),
            },
            "unknown artifact type bindings: Unknown",
        ),
        (
            {"T": ArtifactTypeKey("", 1)},
            "binding 'T'.*non-empty artifact type id",
        ),
        (
            {"T": ArtifactTypeKey("example.value", 0)},
            "binding 'T'.*positive schema version",
        ),
    ],
)
def test_generic_node_contract_rejects_contextual_binding_errors(
    bindings: dict[str, ArtifactTypeKey],
    message: str,
) -> None:
    with pytest.raises(
        NodeContractResolutionError,
        match=f"Node 'example.generic'.*{message}",
    ):
        resolve_node_contracts(GenericNode(), bindings)


@pytest.mark.parametrize("name", ["", " T", "T ", "x" * 256])
def test_artifact_type_variable_rejects_noncanonical_names(name: str) -> None:
    with pytest.raises(ValueError, match="Artifact type variable name"):
        ArtifactTypeVariable(name)


def test_node_contract_resolution_consults_the_binding_validation_hook() -> None:
    blob = ArtifactTypeKey("file.blob", 1)
    jpeg = ArtifactTypeKey("file.jpeg", 1)

    with pytest.raises(
        NodeContractResolutionError,
        match="cannot bind file.blob@1 as T",
    ):
        resolve_node_contracts(ClaimedFormatNode(), {"T": blob})

    resolved = resolve_node_contracts(ClaimedFormatNode(), {"T": jpeg})
    assert resolved.output_contract.ports["items"].produces == jpeg


class ShapeChoiceNode(ExampleNode):
    """A node whose ports take their shape from a config field they name."""

    operator_id = "example.shape_choice"


# No annotation derives a `shape_field`, so these ports are built by hand, and
# `Node.__init_subclass__` re-derives the contracts of every subclass from its
# models, so they are installed once the class exists.
ShapeChoiceNode.input_contract = InputContract(
    model=ExampleInput,
    ports={
        "pages": InputPortSpec(
            name="pages",
            accepts=RASTER_IMAGE.key,
            shape_field="page_shape",
        )
    },
)
ShapeChoiceNode.output_contract = OutputContract(
    model=ExampleOutput,
    ports={
        "pages": OutputPortSpec(
            name="pages",
            produces=RASTER_IMAGE.key,
            shape_field="page_shape",
        )
    },
)


def test_shape_field_port_takes_the_shape_the_config_names() -> None:
    resolved = resolve_node_contracts(ShapeChoiceNode(), {}, {"page_shape": "many"})

    input_port = resolved.input_contract.ports["pages"]
    assert input_port.shape is PortShape.MANY
    assert input_port.accepted_shapes == (PortShape.MANY,)
    assert resolved.output_contract.ports["pages"].shape is PortShape.MANY


def test_shape_field_port_without_its_config_field_keeps_the_declared_shape() -> None:
    for config in ({}, {"other": "many"}, None):
        resolved = resolve_node_contracts(ShapeChoiceNode(), {}, config)

        assert resolved.input_contract.ports["pages"].shape is PortShape.ONE
        assert resolved.input_contract.ports["pages"].accepted_shapes == (
            PortShape.ONE,
        )
        assert resolved.output_contract.ports["pages"].shape is PortShape.ONE


def test_shape_field_refusal_names_the_port_the_field_and_the_value() -> None:
    with pytest.raises(NodeContractResolutionError) as captured:
        resolve_node_contracts(ShapeChoiceNode(), {}, {"page_shape": "both"})

    assert str(captured.value) == (
        "Node 'example.shape_choice' port 'pages' shape field 'page_shape' "
        "must be 'one' or 'many', got 'both'"
    )


@pytest.mark.parametrize("raw_shape", ["", "MANY", 2, 2.0, None, ["many"]])
def test_shape_field_refuses_a_value_that_names_no_shape(raw_shape: object) -> None:
    with pytest.raises(
        NodeContractResolutionError,
        match=(
            r"Node 'example\.shape_choice' port 'pages' shape field 'page_shape' "
            r"must be 'one' or 'many', got "
        ),
    ):
        resolve_node_contracts(ShapeChoiceNode(), {}, {"page_shape": raw_shape})

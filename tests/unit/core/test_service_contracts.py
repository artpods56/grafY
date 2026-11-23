"""Service contracts: nominal protocols, ports, and registration rules."""

from typing import Protocol, override

import pytest
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import (
    Node,
    NodeContractError,
    NodeExecutionContext,
    derive_input_contract,
    derive_output_contract,
    implements_service_contract,
    service_contract,
    validate_service_node,
)
from grafy_core.plugins import Plugin, PluginRegistrationError, PluginRegistry
from grafy_core.service_contracts import marked_contract


@service_contract("test.reader", version=1, title="Test reader")
class FakeReader(Protocol):
    async def read(self) -> str: ...


@service_contract("test.annotator", version=1, title="Test annotator")
class FakeAnnotator(Protocol):
    async def annotate(self) -> str: ...


class BothProviders(FakeReader, FakeAnnotator):
    def __init__(self, *, label: str) -> None:
        self.label = label

    async def read(self) -> str:
        return self.label

    async def annotate(self) -> str:
        return self.label


class DuckTypedReader:
    """Same method name, not a subclass: does not implement the contract."""

    async def read(self) -> str:
        return "duck"


class ProviderConfig(NodeConfig):
    label: str = "a"


class ProviderOutput(NodeOutput):
    reader: BothProviders


class ConsumerInput(NodeInput):
    reader: FakeReader


class ConsumerOutput(NodeOutput):
    text: str


def test_a_provider_output_produces_every_contract_its_class_subclasses() -> None:
    ports = derive_output_contract(ProviderOutput).ports
    assert ports["reader"].kind == "service"
    assert {key.id for key in ports["reader"].service_contracts} == {
        "test.reader",
        "test.annotator",
    }


def test_a_consumer_input_accepts_its_contract() -> None:
    ports = derive_input_contract(ConsumerInput).ports
    own = marked_contract(FakeReader)
    assert own is not None
    assert ports["reader"].kind == "service"
    assert ports["reader"].service_contracts == (own.key,)
    assert ports["reader"].agent_default == "hidden"


def test_a_non_subclass_with_the_same_method_does_not_satisfy_the_contract() -> None:
    assert implements_service_contract(BothProviders(label="ok"), FakeReader)
    assert not implements_service_contract(DuckTypedReader(), FakeReader)


def test_a_service_node_cannot_declare_input_ports() -> None:
    with pytest.raises(NodeContractError, match="cannot declare input ports"):
        validate_service_node(
            "bad.provider@1",
            derive_input_contract(ConsumerInput),
            derive_output_contract(ProviderOutput),
        )


def test_registration_rejects_a_service_node_with_inputs() -> None:
    plugin = Plugin(slug="test.service", title="Service fixtures")
    plugin.register_service_contract(FakeReader)
    plugin.register_service_contract(FakeAnnotator)

    class BadProviderInput(NodeInput):
        unused: FakeReader

    class BadProviderOutput(NodeOutput):
        reader: BothProviders

    with pytest.raises(NodeContractError, match="cannot declare input ports"):

        @plugin.node(operator_id="test.bad_provider", version=1, title="Bad")
        class BadProvider(Node[ProviderConfig, BadProviderInput, BadProviderOutput]):
            """Provide a test node."""

            @override
            async def run(
                self,
                _context: NodeExecutionContext,
                _config: ProviderConfig,
                _inputs: BadProviderInput,
                /,
            ) -> BadProviderOutput:
                raise NotImplementedError


def test_plugin_owns_and_exposes_a_service_contract() -> None:
    plugin = Plugin(slug="test.service", title="Service fixtures")
    plugin.register_service_contract(FakeReader)
    registry = PluginRegistry()
    registry.install(plugin)
    registry.freeze()

    assert [(c.id, c.version, c.title) for c in registry.service_contracts] == [
        ("test.reader", 1, "Test reader")
    ]


def test_a_duplicate_service_contract_is_refused() -> None:
    first = Plugin(slug="test.a", title="A")
    first.register_service_contract(FakeReader)
    second = Plugin(slug="test.b", title="B")
    second.register_service_contract(FakeReader)
    registry = PluginRegistry()
    registry.install(first)
    with pytest.raises(PluginRegistrationError, match="already installed"):
        registry.install(second)


@pytest.mark.parametrize("value", ["", " ", " padded", "padded ", "x" * 256])
def test_service_cache_identity_rejects_invalid_names(value: str) -> None:
    from grafy_core.text_regions import ServiceCacheIdentity

    with pytest.raises(ValueError):
        ServiceCacheIdentity(value, "revision")
    with pytest.raises(ValueError):
        ServiceCacheIdentity("deployment", value)

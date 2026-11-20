"""A service contract is a nominal protocol a node can hand to another node.

The object that satisfies it is built while the consumer runs and is gone when
that computation ends. It is not an artifact: nothing here stores, logs, or
serializes an instance.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic_core import CoreSchema, core_schema

from grafy_core.node_ports import ServiceContractKey

_MARKER = "__service_contract__"


@dataclass(frozen=True, slots=True)
class ServiceContract:
    """One version of a service contract, owned by the plugin that defines it."""

    id: str
    version: int
    title: str
    protocol: type[object]

    @property
    def key(self) -> ServiceContractKey:
        return ServiceContractKey(self.id, self.version)


def service_contract(
    contract_id: str,
    *,
    version: int,
    title: str,
) -> Callable[[type[Any]], type[Any]]:
    """Record ``contract_id``, ``version`` and ``title`` on a protocol class.

    A class implements the contract only when the protocol is in its nominal
    method resolution order. A method of the same name is not an implementation.
    """

    key = ServiceContractKey(contract_id, version)
    normalized_title = title.strip()
    if normalized_title == "" or title != normalized_title:
        raise ValueError(
            "Service contract title must be non-empty without surrounding whitespace"
        )
    if len(normalized_title) > 255:
        raise ValueError("Service contract title must be at most 255 characters")

    def decorate[ProtocolT: type[Any]](protocol: ProtocolT) -> ProtocolT:
        if _MARKER in protocol.__dict__:
            raise ValueError(
                f"{protocol.__name__} already declares a service contract"
            )
        spec = ServiceContract(
            id=key.id,
            version=key.version,
            title=normalized_title,
            protocol=protocol,
        )
        setattr(protocol, _MARKER, spec)
        _install_nominal_schema(protocol)
        return protocol

    return decorate


def marked_contract(cls: type[object]) -> ServiceContract | None:
    """The contract declared on ``cls`` itself, ignoring contracts it inherits."""

    raw = cls.__dict__.get(_MARKER)
    if isinstance(raw, ServiceContract):
        return raw
    return None


def produced_contracts(cls: type[object]) -> tuple[ServiceContract, ...]:
    """Every contract in ``cls``'s nominal method resolution order, once each."""

    found: list[ServiceContract] = []
    seen: set[ServiceContractKey] = set()
    for base in cls.__mro__:
        spec = marked_contract(base)
        if spec is None or spec.key in seen:
            continue
        seen.add(spec.key)
        found.append(spec)
    return tuple(found)


def implements_service_contract(value: object, contract: type[object]) -> bool:
    """Whether ``value`` is a nominal instance of ``contract``.

    Membership is identity in the instance's method resolution order. A class
    that only defines a method of the same name does not implement the contract.
    """

    return any(base is contract for base in type(value).__mro__)


def _install_nominal_schema(protocol: type[object]) -> None:
    """Let a node model accept nominal instances of this protocol.

    Pydantic would otherwise treat the protocol structurally, or refuse to
    validate it at all. The source type of the annotation is what must appear
    in the value's method resolution order, so a field typed as the protocol
    accepts its subclasses and a field typed as a subclass accepts that subclass.
    """

    def get_schema(
        cls: type[object],
        source: type[object],
        handler: object,
    ) -> CoreSchema:
        del cls, handler

        def validate(value: object) -> object:
            if implements_service_contract(value, source):
                return value
            raise ValueError(f"Expected an instance of {source.__qualname__}")

        return core_schema.no_info_plain_validator_function(validate)

    setattr(protocol, "__get_pydantic_core_schema__", classmethod(get_schema))


__all__ = [
    "ServiceContract",
    "implements_service_contract",
    "marked_contract",
    "produced_contracts",
    "service_contract",
]

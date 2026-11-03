"""Deployment facts for one Project document (ADR 0020).

The fingerprint function needs three things the document cannot say: what the
node's implementation is, whether its output may be reused, and which secret
state it runs under. This module answers all three for one document at one
moment: :meth:`ApplicationFactsFactory.for_project` does the asynchronous part
(reading secret revisions) once and hands back a frozen, synchronous
``FingerprintFacts`` the kernel can call for every instance.

Two rules from ADR 0020 shape the answers:

* **A Graph boundary runs no family code.** ``graph.input`` and ``graph.output``
  are host-owned pass-throughs, so their implementation identity is the operator
  id, its version and the execution epoch alone, and what comes out is exactly
  what went in: cache policy ``EXACT``.
* **A node this build cannot describe is an error, never a default.** A missing
  implementation digest or registration raises
  :class:`~grafy_api.runs.ports.RunRejectedError` with code ``unknown_operator``.
  A placeholder digest or a silent ``NEVER`` would hand a wrong result back as
  fresh, which is the one failure this design cannot take back.

Secret revisions are resolved by ``(project, graph, node)``, never by call path:
a secret belongs to the node, and a Graph called twice runs under one
credential, so both calls must fingerprint the same way.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from grafy_api.runs.ports import RunRejectedError
from grafy_core.domain.graph_documents import GraphNode
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.kernel.facts import FingerprintFacts
from grafy_core.kernel.implementation_identity import (
    EXECUTION_EPOCH,
    RegistryImplementationDigests,
)
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    ProjectDocument,
)
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeRegistration,
    NodeSecretInput,
    PluginRegistry,
    UnknownOperatorError,
)

#: The revision a node runs under while its secret has never been set. Setting
#: one moves the fingerprint without any secret value entering it.
UNAVAILABLE_SECRET_REVISION = "unavailable"

_BOUNDARY_OPERATORS: frozenset[str] = frozenset(
    {GRAPH_INPUT_OPERATOR_ID, GRAPH_OUTPUT_OPERATOR_ID}
)
_NO_SECRETS: Mapping[str, str] = MappingProxyType({})


def _is_boundary(node: GraphNode) -> bool:
    """Is this node one of the host-owned Graph interface pass-throughs?"""
    return node.operator_id in _BOUNDARY_OPERATORS


def _operator_named(node: GraphNode) -> str:
    return f"{node.operator_id}@{node.operator_version}"


def _boundary_digest(node: GraphNode) -> str:
    """Implementation identity of a boundary operator: nothing but its own name."""
    identity = f"{node.operator_id}@{node.operator_version}|{EXECUTION_EPOCH}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _catalog_registration(
    registry: PluginRegistry,
    node: GraphNode,
) -> NodeRegistration:
    """The catalog entry a node runs, or the rejection that it has none."""
    try:
        return registry.node_registration(
            node.operator_id,
            node.operator_version,
        )
    except UnknownOperatorError:
        raise RunRejectedError(
            "unknown_operator",
            f"No registration for operator {_operator_named(node)}",
        ) from None


def _effective_config(
    registration: NodeRegistration,
    node: GraphNode,
) -> Mapping[str, JsonValue]:
    """The node's configuration as its own contract sees it.

    A secret may name any configuration field as a dependency, including one the
    document omits and the contract supplies a default for, so the validated
    model is the only place those dependencies can be read from.
    """
    model = registration.node_class.config_contract.model
    try:
        validated = model.model_validate(node.config)
    except ValidationError as exc:
        raise RunRejectedError(
            "invalid_document",
            f"Node {node.id!r} config does not satisfy operator "
            f"{_operator_named(node)}: {exc}",
        ) from exc
    dumped: dict[str, JsonValue] = validated.model_dump(mode="json")
    return dumped


class SecretRevisionResolver(Protocol):
    """The revision one node secret is currently at.

    The identity carries project, Graph and node — never a call path — because
    the secret belongs to the node, not to the route taken to reach it.
    """

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ApplicationFacts:
    """``FingerprintFacts`` for one document: catalog, digests, secret revisions."""

    registry: PluginRegistry
    digests: RegistryImplementationDigests
    secrets: Mapping[tuple[str, str], Mapping[str, str]]

    def implementation_digest(self, node: GraphNode) -> str:
        if _is_boundary(node):
            return _boundary_digest(node)
        try:
            return self.digests.implementation_digest(node)
        except KeyError:
            raise RunRejectedError(
                "unknown_operator",
                f"No implementation digest for operator {_operator_named(node)}",
            ) from None

    def cache_policy(self, node: GraphNode) -> NodeCachePolicy:
        if _is_boundary(node):
            return NodeCachePolicy.EXACT
        return _catalog_registration(self.registry, node).cache_policy

    def secret_revisions(self, key: InstanceKey) -> Mapping[str, str]:
        return self.secrets.get((key.graph_id, key.node_id), _NO_SECRETS)


class ApplicationFactsFactory:
    """Builds :class:`ApplicationFacts` for one Project document.

    The catalog and its implementation digests are deployment-wide and built at
    startup; secret revisions are the only per-document reading, and they are
    taken once per ``(graph, node)`` here rather than once per fingerprint.
    """

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        digests: RegistryImplementationDigests,
        secrets: SecretRevisionResolver,
    ) -> None:
        self._registry = registry
        self._digests = digests
        self._secrets = secrets

    async def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        document: ProjectDocument,
    ) -> FingerprintFacts:
        secrets = await self._secret_revisions(
            workspace_id=workspace_id,
            project_id=project_id,
            document=document,
        )
        return ApplicationFacts(
            registry=self._registry,
            digests=self._digests,
            secrets=secrets,
        )

    async def _secret_revisions(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        document: ProjectDocument,
    ) -> Mapping[tuple[str, str], Mapping[str, str]]:
        """Every declared secret of every node, resolved once per ``(graph, node)``.

        A node with no declared secret inputs contributes nothing. A node this
        build does not register stops the whole document, rather than only the
        Graph someone happened to run: the catalog cannot describe any node of
        this Project well enough for its fingerprints to be trusted, and an
        operator id is not scoped to one Graph.

        Unlike per-invocation execution, nothing here waits for cache policy
        ``EXACT``: a secret revision is part of what the node runs, so it enters
        the fingerprint of a node that never reuses its result too.
        """
        resolved: dict[tuple[str, str], Mapping[str, str]] = {}
        for graph in document.graphs:
            for node in graph.document.nodes:
                if node.kind == CALL_NODE_KIND or _is_boundary(node):
                    continue
                registration = _catalog_registration(self._registry, node)
                if not registration.secret_inputs:
                    continue
                effective = _effective_config(registration, node)
                resolved[(graph.id, node.id)] = MappingProxyType(
                    {
                        secret_input.name: await self._cache_revision(
                            workspace_id=workspace_id,
                            project_id=project_id,
                            graph_id=graph.id,
                            node_id=node.id,
                            secret_input=secret_input,
                            effective_config=effective,
                        )
                        for secret_input in registration.secret_inputs
                    }
                )
        return MappingProxyType(resolved)

    async def _cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        secret_input: NodeSecretInput,
        effective_config: Mapping[str, JsonValue],
    ) -> str:
        missing = sorted(set(secret_input.config_dependencies) - set(effective_config))
        if missing:
            raise RunRejectedError(
                "invalid_document",
                f"Node {node_id!r} of graph {graph_id!r} cannot resolve the "
                f"dependencies of secret {secret_input.name!r}: " + ", ".join(missing),
            )
        dependencies = {
            dependency: effective_config[dependency]
            for dependency in secret_input.config_dependencies
        }
        try:
            return await self._secrets.cache_revision(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                node_id=node_id,
                name=secret_input.name,
                dependencies=dependencies,
            )
        except NodeSecretUnavailableError:
            # No credential yet is a state of its own, not an absence of one:
            # recorded as a revision, so setting the secret moves the fingerprint.
            return UNAVAILABLE_SECRET_REVISION


__all__ = [
    "UNAVAILABLE_SECRET_REVISION",
    "ApplicationFacts",
    "ApplicationFactsFactory",
    "SecretRevisionResolver",
]

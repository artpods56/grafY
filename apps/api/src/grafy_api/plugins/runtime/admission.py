"""Deployment-owned admission policy for exact Plugin releases."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from grafy_core.artifact_contracts import INTEGER_VALUE, RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import ArtifactBundleFormat
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginNodeContract,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.plugin_selection import (
    PluginReleaseSelection,
)
from grafy_core.table_contracts import TABLE_DATA

from grafy_api.system_host_bindings import SystemHostPluginBinding
from grafy_api.plugins.runtime.egress import (
    PluginEgressBrokerPolicy,
    PluginEgressProtocol,
)
from grafy_api.plugins.runtime.network_policy import (
    NetworkAccessPlane,
    NetworkAccessProfile,
    NetworkPolicy,
    NetworkProfileMode,
    NetworkRejectionReason,
)
from grafy_api.plugins.profiles import PluginRuntimeProfile


PluginNonRunnableReason = Literal[
    "revoked",
    "missing_runtime_artifact",
    "incompatible_protocol",
    "unsupported_runtime_profile",
    "unsupported_capabilities",
    "unsupported_artifact_type",
    "plugin_runtime_unavailable",
    "host_binding_mismatch",
    "network_profile_unassigned",
    "network_profile_disabled",
    "network_destination_undeclared",
    "network_dynamic_destination_denied",
    "network_destination_not_allowlisted",
    "network_origin_limit_exceeded",
]

_DEFAULT_PLATFORM_ARTIFACT_CONTRACTS = tuple(
    PluginArtifactTypeContract.from_spec(spec)
    for spec in (INTEGER_VALUE, TEXT_VALUE, RASTER_IMAGE, TABLE_DATA)
)
ISOLATED_BASE_CAPABILITIES = frozenset(
    {
        PluginRuntimeCapability.NODE_SECRETS,
        PluginRuntimeCapability.STAGED_UPLOADS,
        PluginRuntimeCapability.UNTRUSTED_SQL,
    }
)
HOST_BASE_CAPABILITIES = frozenset(
    {
        PluginRuntimeCapability.NODE_SECRETS,
        PluginRuntimeCapability.STAGED_UPLOADS,
    }
)


@dataclass(frozen=True, slots=True)
class PluginNetworkEgressPolicy:
    """Deployment-owned proxy boundary for allowlisted guest HTTP egress."""

    proxy_adapter_available: bool = False
    broker: PluginEgressBrokerPolicy = PluginEgressBrokerPolicy()

    @property
    def available(self) -> bool:
        return (
            self.proxy_adapter_available
            and self.broker.available
            and bool(
                self.broker.destinations_for(PluginEgressProtocol.HTTP)
                or self.broker.destinations_for(PluginEgressProtocol.HTTPS)
            )
        )


@dataclass(frozen=True, slots=True)
class PluginPostgresqlEgressPolicy:
    """Separate destination-scoped TCP broker; never generic HTTP CONNECT."""

    broker: PluginEgressBrokerPolicy = PluginEgressBrokerPolicy()
    tcp_adapter_available: bool = False

    @property
    def available(self) -> bool:
        return (
            self.tcp_adapter_available
            and self.broker.available
            and bool(self.broker.destinations_for(PluginEgressProtocol.POSTGRESQL))
        )


class ReleaseExecutionRoute(StrEnum):
    """Runtime route selected for an admitted immutable release."""

    ISOLATED = "isolated"
    IN_PROCESS = "in-process"


@dataclass(frozen=True, slots=True)
class ReleaseExecutionRejection:
    """Stable fail-closed reason shared by catalog and execution boundaries."""

    reason: PluginNonRunnableReason
    detail: str


type ReleaseExecutionDecision = ReleaseExecutionRoute | ReleaseExecutionRejection


@dataclass(frozen=True, slots=True)
class ReleaseExecutionAdmission:
    """Decide whether this deployment can execute one exact release."""

    isolated_adapter_available: bool
    runtime_profile: str | None
    # Backwards-compatible isolated-runtime policy. Host bindings have a
    # deliberately separate allowlist because they execute in the API process.
    supported_capabilities: frozenset[PluginRuntimeCapability] = frozenset()
    network_egress: PluginNetworkEgressPolicy = PluginNetworkEgressPolicy()
    postgresql_egress: PluginPostgresqlEgressPolicy = PluginPostgresqlEgressPolicy()
    # Deployment-owned profiles and assignments; the release may request
    # authority but only this policy grants it.
    network_policy: NetworkPolicy = field(default_factory=NetworkPolicy)
    supported_bundle_adapters: frozenset[tuple[ArtifactBundleFormat, int]] = frozenset(
        {
            ("binary-file", 1),
            ("inline-json", 1),
            ("object-set", 1),
            ("table-bundle", 1),
        }
    )
    platform_artifact_contracts: tuple[PluginArtifactTypeContract, ...] = (
        _DEFAULT_PLATFORM_ARTIFACT_CONTRACTS
    )
    system_host_bindings: tuple[SystemHostPluginBinding, ...] = ()
    host_supported_capabilities: frozenset[PluginRuntimeCapability] = frozenset()
    host_network_egress: PluginNetworkEgressPolicy = PluginNetworkEgressPolicy()

    def decide(
        self,
        release: InstalledPluginRelease,
        *,
        node_contract: PluginNodeContract | None = None,
        selection: PluginReleaseSelection | None = None,
        revocation: PluginReleaseRevocation | None = None,
    ) -> ReleaseExecutionDecision:
        if revocation is not None:
            return ReleaseExecutionRejection(
                reason="revoked",
                detail=(
                    "This exact Plugin release was permanently revoked "
                    f"({revocation.reason.value})."
                ),
            )
        artifact = release.release.runtime_artifact
        if artifact is None:
            return ReleaseExecutionRejection(
                reason="missing_runtime_artifact",
                detail="This release has no immutable runtime image.",
            )
        if release.release.protocol_digest != plugin_protocol_digest():
            return ReleaseExecutionRejection(
                reason="incompatible_protocol",
                detail="This release uses an incompatible invocation protocol.",
            )
        contracts = (
            release.release.catalog.nodes if node_contract is None else (node_contract,)
        )
        required_capabilities = (
            set(release.release.capabilities.capabilities)
            if node_contract is None
            else set(node_contract.required_capabilities)
        )
        has_secret_inputs = any(contract.secret_inputs for contract in contracts)
        missing_secret_capability = (
            has_secret_inputs
            and PluginRuntimeCapability.NODE_SECRETS not in required_capabilities
        )
        if missing_secret_capability:
            return ReleaseExecutionRejection(
                reason="unsupported_capabilities",
                detail="Unsupported Plugin capabilities: undeclared node secrets.",
            )

        effective_isolated_capabilities = set(self.supported_capabilities)
        if not self.postgresql_egress.available:
            effective_isolated_capabilities.discard(
                PluginRuntimeCapability.POSTGRESQL_EGRESS
            )
        network_requested = (
            PluginRuntimeCapability.NETWORK_EGRESS in required_capabilities
        )
        broker_configured = self.network_egress.broker.broker_image is not None
        if network_requested and broker_configured:
            network_rejection = self._network_egress_rejection(release, node_contract)
            if network_rejection is not None:
                return network_rejection
            effective_isolated_capabilities.add(PluginRuntimeCapability.NETWORK_EGRESS)
        elif network_requested:
            effective_isolated_capabilities.discard(
                PluginRuntimeCapability.NETWORK_EGRESS
            )
        unsupported_isolated_capabilities = sorted(
            required_capabilities - effective_isolated_capabilities,
            key=lambda capability: capability.value,
        )
        if unsupported_isolated_capabilities:
            rendered = ", ".join(
                capability.value for capability in unsupported_isolated_capabilities
            )
            return ReleaseExecutionRejection(
                reason="unsupported_capabilities",
                detail=f"Unsupported isolated Plugin capabilities: {rendered}.",
            )

        artifact_contracts = {
            (artifact_type.key.id, artifact_type.key.schema_version): artifact_type
            for artifact_type in (
                *self.platform_artifact_contracts,
                *release.release.catalog.artifact_types,
                *release.release.catalog.artifact_type_dependencies,
            )
        }
        unsupported_types: set[str] = set()
        for contract in contracts:
            for port in (*contract.inputs, *contract.outputs):
                if port.artifact_type is None:
                    unsupported_types.add(
                        f"type variable {port.artifact_type_variable!r}"
                    )
                    continue
                key = (port.artifact_type.id, port.artifact_type.schema_version)
                artifact_contract = artifact_contracts.get(key)
                if artifact_contract is None:
                    unsupported_types.add(f"{key[0]}@{key[1]} (undeclared)")
                    continue
                adapter = (
                    artifact_contract.bundle.format,
                    artifact_contract.bundle.version,
                )
                if adapter not in self.supported_bundle_adapters:
                    unsupported_types.add(
                        f"{key[0]}@{key[1]} ({adapter[0]}@{adapter[1]})"
                    )
        if unsupported_types:
            return ReleaseExecutionRejection(
                reason="unsupported_artifact_type",
                detail=(
                    "No portable Plugin bundle is available for: "
                    + ", ".join(sorted(unsupported_types))
                    + "."
                ),
            )

        if (
            self.runtime_profile is None
            or release.release.runtime_profile != self.runtime_profile
            or release.release.profile_digest
            != plugin_profile_digest(self.runtime_profile)
        ):
            return ReleaseExecutionRejection(
                reason="unsupported_runtime_profile",
                detail=(
                    f"Runtime profile {release.release.runtime_profile!r} is not available in "
                    "this deployment."
                ),
            )
        if not self.isolated_adapter_available:
            return ReleaseExecutionRejection(
                reason="plugin_runtime_unavailable",
                detail="The isolated Plugin runtime is not available.",
            )
        return ReleaseExecutionRoute.ISOLATED

    def _network_egress_rejection(
        self,
        release: InstalledPluginRelease,
        node_contract: PluginNodeContract | None,
    ) -> ReleaseExecutionRejection | None:
        """Fail closed when the assigned profile cannot satisfy the request."""

        if node_contract is not None:
            if PluginRuntimeCapability.NETWORK_EGRESS not in set(
                node_contract.required_capabilities
            ):
                return None
            network_contracts = (node_contract,)
        else:
            network_contracts = tuple(
                contract
                for contract in release.release.catalog.nodes
                if PluginRuntimeCapability.NETWORK_EGRESS
                in set(contract.required_capabilities)
            )
            if not network_contracts:
                return None
        profile = self.network_policy.resolve(
            NetworkAccessPlane.PLUGIN_EXECUTION,
            scope=release.installation.scope,
            workspace_id=release.installation.workspace_id,
            slug=release.release.slug,
            revision=release.release.revision,
        )
        if profile is None:
            return ReleaseExecutionRejection(
                reason=NetworkRejectionReason.PROFILE_UNASSIGNED,
                detail="No network profile is assigned for this Plugin release.",
            )
        if not profile.grants_http_authority:
            return ReleaseExecutionRejection(
                reason=NetworkRejectionReason.PROFILE_DISABLED,
                detail=(
                    f"Assigned network profile {profile.name!r} grants no HTTP egress."
                ),
            )
        if node_contract is not None:
            return _node_network_rejection(profile, node_contract)
        if all(
            _node_has_network_source(profile, contract) is False
            for contract in network_contracts
        ):
            if all(
                contract.http_egress is not None
                and contract.http_egress.dynamic_destinations
                for contract in network_contracts
            ):
                return ReleaseExecutionRejection(
                    reason=NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED,
                    detail=(
                        "Every network-capable node requests dynamic "
                        "destinations, which the assigned profile does not "
                        "satisfy."
                    ),
                )
            return ReleaseExecutionRejection(
                reason=NetworkRejectionReason.DESTINATION_UNDECLARED,
                detail=(
                    "No network-capable node in this release can obtain a "
                    "destination under the assigned profile."
                ),
            )
        return None


def isolated_release_admission(
    *,
    profile: PluginRuntimeProfile,
    egress_policy: PluginEgressBrokerPolicy,
    network_policy: NetworkPolicy,
    system_host_bindings: tuple[SystemHostPluginBinding, ...] = (),
    supported_capabilities: frozenset[PluginRuntimeCapability] = (
        ISOLATED_BASE_CAPABILITIES
    ),
) -> ReleaseExecutionAdmission:
    """Build the admission policy shared by publication and execution."""

    effective_capabilities = set(supported_capabilities)
    effective_capabilities.update(profile.native_capabilities)
    for native_capability in (
        PluginRuntimeCapability.NATIVE_GDAL,
        PluginRuntimeCapability.NATIVE_TESSERACT,
    ):
        if native_capability not in profile.native_capabilities:
            effective_capabilities.discard(native_capability)
    network_egress = PluginNetworkEgressPolicy(
        proxy_adapter_available=egress_policy.broker_image is not None,
        broker=egress_policy,
    )
    postgresql_egress = PluginPostgresqlEgressPolicy(
        tcp_adapter_available=bool(
            egress_policy.destinations_for(PluginEgressProtocol.POSTGRESQL)
        ),
        broker=egress_policy,
    )
    if egress_policy.broker_image is not None:
        effective_capabilities.add(PluginRuntimeCapability.NETWORK_EGRESS)
    if postgresql_egress.available:
        effective_capabilities.add(PluginRuntimeCapability.POSTGRESQL_EGRESS)
    return ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile=profile.name,
        supported_capabilities=frozenset(effective_capabilities),
        network_egress=network_egress,
        postgresql_egress=postgresql_egress,
        network_policy=network_policy,
        system_host_bindings=system_host_bindings,
        host_supported_capabilities=HOST_BASE_CAPABILITIES,
    )


def _node_has_network_source(
    profile: NetworkAccessProfile,
    contract: PluginNodeContract,
) -> bool:
    http_egress = contract.http_egress
    if http_egress is None:
        return profile.mode is NetworkProfileMode.CURATED and bool(
            profile.allowed_origins
        )
    if http_egress.dynamic_destinations:
        return False
    if not http_egress.configured_inputs:
        return False
    if profile.mode is NetworkProfileMode.CURATED:
        return bool(profile.allowed_origins)
    return True


def _node_network_rejection(
    profile: NetworkAccessProfile,
    contract: PluginNodeContract,
) -> ReleaseExecutionRejection | None:
    http_egress = contract.http_egress
    if http_egress is None:
        if profile.mode is NetworkProfileMode.CURATED and profile.allowed_origins:
            return None
        return ReleaseExecutionRejection(
            reason=NetworkRejectionReason.DESTINATION_UNDECLARED,
            detail=(
                "Historical releases without an HTTP egress contract may only "
                "run under a curated compatibility profile."
            ),
        )
    if http_egress.dynamic_destinations:
        if profile.allows_dynamic_destinations:
            return ReleaseExecutionRejection(
                reason=NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED,
                detail=(
                    "The deployment has not enabled the open-public broker "
                    "mode required to satisfy dynamic destination requests."
                ),
            )
        return ReleaseExecutionRejection(
            reason=NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED,
            detail=(
                "Dynamic destinations require an explicit open-public "
                f"profile assignment; assigned profile is {profile.name!r}."
            ),
        )
    if not http_egress.configured_inputs:
        return ReleaseExecutionRejection(
            reason=NetworkRejectionReason.DESTINATION_UNDECLARED,
            detail=(
                "The node declares no configured URL field or dynamic "
                "destinations, so no origin can be granted."
            ),
        )
    if len(http_egress.configured_inputs) > profile.limits.max_origins_per_execution:
        return ReleaseExecutionRejection(
            reason=NetworkRejectionReason.ORIGIN_LIMIT_EXCEEDED,
            detail=(
                f"{len(http_egress.configured_inputs)} configured URL fields "
                "exceed the profile origin limit."
            ),
        )
    if profile.mode is NetworkProfileMode.CURATED and not profile.allowed_origins:
        return ReleaseExecutionRejection(
            reason=NetworkRejectionReason.DESTINATION_NOT_ALLOWLISTED,
            detail=(
                f"Assigned curated profile {profile.name!r} declares no "
                "allowed origins."
            ),
        )
    return None


__all__ = [
    "PluginNonRunnableReason",
    "PluginNetworkEgressPolicy",
    "PluginPostgresqlEgressPolicy",
    "ReleaseExecutionAdmission",
    "ReleaseExecutionDecision",
    "ReleaseExecutionRejection",
    "ReleaseExecutionRoute",
]

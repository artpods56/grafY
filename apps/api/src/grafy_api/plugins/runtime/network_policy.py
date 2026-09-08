"""Deployment-owned network access profiles and their effective authority.

Executable code may request network authority; only the deployment assigns
profiles. The effective authority attached to one sandbox is always an
intersection of the release request, the assigned profile, the deployment's
hard limits, and the invocation-derived destinations. No input may widen a
limit imposed above it.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Mapping
from uuid import UUID

import tomllib

from cryptography import x509
from grafy_core.domain.plugin_releases import PluginNodeContract
from grafy_core.domain.plugin_identity import PluginReleaseScope

from grafy_api.plugins.runtime.egress import (
    PLUGIN_EGRESS_CONNECT_TIMEOUT_SECONDS,
    PLUGIN_EGRESS_CONNECTION_LIMIT,
    PLUGIN_EGRESS_IDLE_TIMEOUT_SECONDS,
    PLUGIN_EGRESS_MAX_HEADER_BYTES,
    PLUGIN_EGRESS_MAX_REQUEST_BYTES,
    PLUGIN_EGRESS_MAX_RESPONSE_BYTES,
    PluginEgressDestination,
    PluginEgressLimits,
    PluginEgressProtocol,
)


class NetworkPolicyError(ValueError):
    """A deployment network policy or manifest is invalid."""


class NetworkAccessPlane(StrEnum):
    """One lifecycle boundary where code may attempt network access."""

    AGENT_AUTHORING = "agent-authoring"
    PUBLICATION = "publication"
    PLUGIN_EXECUTION = "plugin-execution"


class NetworkProfileMode(StrEnum):
    DISABLED = "disabled"
    OFFLINE = "offline"
    CONFIGURED_PUBLIC = "configured-public"
    CURATED = "curated"
    DEPENDENCIES = "dependencies"
    CUSTOM_ALLOWLIST = "custom-allowlist"
    OPEN_PUBLIC = "open-public"


_EXECUTION_MODES = frozenset(
    {
        NetworkProfileMode.DISABLED,
        NetworkProfileMode.CONFIGURED_PUBLIC,
        NetworkProfileMode.CURATED,
        NetworkProfileMode.OPEN_PUBLIC,
    }
)
_NON_EXECUTION_MODES = frozenset(
    {
        NetworkProfileMode.OFFLINE,
        NetworkProfileMode.DEPENDENCIES,
        NetworkProfileMode.CUSTOM_ALLOWLIST,
        NetworkProfileMode.OPEN_PUBLIC,
    }
)

PLANE_MODES: dict[NetworkAccessPlane, frozenset[NetworkProfileMode]] = {
    NetworkAccessPlane.PLUGIN_EXECUTION: _EXECUTION_MODES,
    NetworkAccessPlane.PUBLICATION: _NON_EXECUTION_MODES,
    NetworkAccessPlane.AGENT_AUTHORING: _NON_EXECUTION_MODES,
}

DISABLED_MODES = frozenset({NetworkProfileMode.DISABLED, NetworkProfileMode.OFFLINE})

_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_MAX_CA_BUNDLE_BYTES = 1_048_576
_CERTIFICATE_PEM_BLOCK = re.compile(
    rb"-----BEGIN CERTIFICATE-----\r?\n"
    rb"(?:[A-Za-z0-9+/=]+\r?\n)+"
    rb"-----END CERTIFICATE-----"
)

_DEFAULT_PYTHON_PACKAGE_ORIGINS = tuple(
    sorted(
        {
            PluginEgressDestination.parse("https://pypi.org:443"),
            PluginEgressDestination.parse("https://files.pythonhosted.org:443"),
        }
    )
)


class NetworkRejectionReason(StrEnum):
    """Machine-stable reasons a network authority request is denied."""

    PROFILE_UNASSIGNED = "network_profile_unassigned"
    PROFILE_DISABLED = "network_profile_disabled"
    DESTINATION_UNDECLARED = "network_destination_undeclared"
    DYNAMIC_DESTINATION_DENIED = "network_dynamic_destination_denied"
    DESTINATION_NOT_ALLOWLISTED = "network_destination_not_allowlisted"
    DESTINATION_UNSAFE = "network_destination_unsafe"
    ORIGIN_LIMIT_EXCEEDED = "network_origin_limit_exceeded"
    SANDBOX_VARIANT_LIMIT_EXCEEDED = "network_sandbox_variant_limit_exceeded"
    BROKER_UNAVAILABLE = "network_broker_unavailable"
    DESTINATION_DENIED = "network_destination_denied"


@dataclass(frozen=True, slots=True)
class NetworkCaBundle:
    """Deployment-owned CA trust captured immutably by content identity."""

    path: Path = field(repr=False)
    content: bytes = field(repr=False)
    sha256: str

    def __post_init__(self) -> None:
        if not self.path.is_absolute() or self.sha256 != sha256(
            self.content
        ).hexdigest():
            raise NetworkPolicyError("Network CA bundle identity is invalid")
        _validate_ca_bundle_content(self.content)

    @classmethod
    def load(cls, path: Path) -> "NetworkCaBundle":
        try:
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                raise OSError
            content = path.read_bytes()
        except OSError:
            raise NetworkPolicyError(
                "Network CA bundle is not a readable absolute regular file"
            ) from None
        return cls(
            path=path,
            content=content,
            sha256=sha256(content).hexdigest(),
        )


def _validate_ca_bundle_content(content: bytes) -> None:
    if not content or len(content) > _MAX_CA_BUNDLE_BYTES:
        raise NetworkPolicyError(
            "Network CA bundle must contain certificate PEM blocks only"
        )
    offset = 0
    certificate_count = 0
    for match in _CERTIFICATE_PEM_BLOCK.finditer(content):
        if content[offset:match.start()].strip():
            raise NetworkPolicyError(
                "Network CA bundle must contain certificate PEM blocks only"
            )
        try:
            x509.load_pem_x509_certificate(match.group())
        except ValueError:
            raise NetworkPolicyError(
                "Network CA bundle must contain valid certificate PEM blocks only"
            ) from None
        offset = match.end()
        certificate_count += 1
    if certificate_count == 0 or content[offset:].strip():
        raise NetworkPolicyError(
            "Network CA bundle must contain certificate PEM blocks only"
        )


@dataclass(frozen=True, slots=True)
class NetworkProfileLimits:
    """Bounded resource ceilings one profile attaches to a sandbox."""

    max_origins_per_execution: int = 8
    connection_limit: int = PLUGIN_EGRESS_CONNECTION_LIMIT
    max_header_bytes: int = PLUGIN_EGRESS_MAX_HEADER_BYTES
    max_request_bytes: int = PLUGIN_EGRESS_MAX_REQUEST_BYTES
    max_response_bytes: int = PLUGIN_EGRESS_MAX_RESPONSE_BYTES
    connect_timeout_seconds: int = PLUGIN_EGRESS_CONNECT_TIMEOUT_SECONDS
    idle_timeout_seconds: int = PLUGIN_EGRESS_IDLE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _check_range("max_origins_per_execution", self.max_origins_per_execution, 1, 128)
        _check_range("connection_limit", self.connection_limit, 1, 1_024)
        _check_range("max_header_bytes", self.max_header_bytes, 1_024, 1_048_576)
        _check_range(
            "max_request_bytes", self.max_request_bytes, 1_024, 1_073_741_824
        )
        _check_range(
            "max_response_bytes", self.max_response_bytes, 1_024, 1_073_741_824
        )
        _check_range(
            "connect_timeout_seconds", self.connect_timeout_seconds, 1, 60
        )
        _check_range("idle_timeout_seconds", self.idle_timeout_seconds, 1, 900)

    def broker_limits(self) -> PluginEgressLimits:
        return PluginEgressLimits(
            connection_limit=self.connection_limit,
            max_header_bytes=self.max_header_bytes,
            max_request_bytes=self.max_request_bytes,
            max_response_bytes=self.max_response_bytes,
            connect_timeout_seconds=self.connect_timeout_seconds,
            idle_timeout_seconds=self.idle_timeout_seconds,
        )

    def canonical_document(self) -> dict[str, object]:
        return {
            "max_origins_per_execution": self.max_origins_per_execution,
            "connection_limit": self.connection_limit,
            "max_header_bytes": self.max_header_bytes,
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class NetworkAccessProfile:
    """One named, plane-bound network authority a deployment may assign.

    The identity is ``(plane, name)`` so every plane may define a profile
    named ``offline``. Display labels never affect the policy digest.
    """

    name: str
    plane: NetworkAccessPlane
    mode: NetworkProfileMode
    public_address_only: bool = True
    https_only: bool = True
    allowed_origins: tuple[PluginEgressDestination, ...] = ()
    ca_bundle: NetworkCaBundle | None = None
    limits: NetworkProfileLimits = field(default_factory=NetworkProfileLimits)
    label: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if (
            not _PROFILE_NAME.fullmatch(self.name)
            or len(self.name) > 100
        ):
            raise NetworkPolicyError(
                "Network profile names must match ^[a-z][a-z0-9-]*$"
            )
        if self.mode not in PLANE_MODES[self.plane]:
            raise NetworkPolicyError(
                f"Profile mode {self.mode.value!r} is invalid for plane "
                f"{self.plane.value!r}"
            )
        origins = tuple(sorted(set(self.allowed_origins)))
        if not self.public_address_only and (
            self.plane is not NetworkAccessPlane.PLUGIN_EXECUTION
            or self.mode is not NetworkProfileMode.CURATED
            or not origins
        ):
            raise NetworkPolicyError(
                "Non-public address space requires exact curated Plugin execution "
                "origins"
            )
        if self.ca_bundle is not None and (
            self.plane is not NetworkAccessPlane.PLUGIN_EXECUTION
            or self.mode is not NetworkProfileMode.CURATED
            or not origins
        ):
            raise NetworkPolicyError(
                "Network CA bundles require exact curated Plugin execution origins"
            )
        if any(origin.protocol is PluginEgressProtocol.POSTGRESQL for origin in origins):
            raise NetworkPolicyError(
                "Network profiles may only authorize HTTP(S) origins"
            )
        if self.https_only and any(
            origin.protocol is not PluginEgressProtocol.HTTPS
            for origin in origins
        ):
            raise NetworkPolicyError(
                f"Profile {self.name!r} is HTTPS-only but declares plain HTTP origins"
            )
        object.__setattr__(self, "allowed_origins", origins)

    @property
    def grants_http_authority(self) -> bool:
        return self.mode not in DISABLED_MODES

    @property
    def allows_dynamic_destinations(self) -> bool:
        return self.mode is NetworkProfileMode.OPEN_PUBLIC

    @property
    def policy_digest(self) -> str:
        """SHA-256 of every normalized setting that changes network authority."""

        document = {
            "name": self.name,
            "plane": self.plane.value,
            "mode": self.mode.value,
            "public_address_only": self.public_address_only,
            "https_only": self.https_only,
            "allowed_origins": [
                {
                    "protocol": origin.protocol.value,
                    "host": origin.host,
                    "port": origin.port,
                }
                for origin in self.allowed_origins
            ],
            "ca_bundle_sha256": (
                None if self.ca_bundle is None else self.ca_bundle.sha256
            ),
            "limits": self.limits.canonical_document(),
        }
        payload = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(payload).hexdigest()


def built_in_offline_profile(plane: NetworkAccessPlane) -> NetworkAccessProfile:
    mode = (
        NetworkProfileMode.DISABLED
        if plane is NetworkAccessPlane.PLUGIN_EXECUTION
        else NetworkProfileMode.OFFLINE
    )
    return NetworkAccessProfile(
        name="offline",
        plane=plane,
        mode=mode,
        https_only=True,
    )


@dataclass(frozen=True, slots=True)
class NetworkProfileAssignment:
    """One deployment-owned mapping from release identity to profile name."""

    plane: NetworkAccessPlane
    profile: str
    scope: PluginReleaseScope | None = None
    workspace_id: UUID | None = None
    slug: str | None = None
    revision: int | None = None

    def __post_init__(self) -> None:
        if not _PROFILE_NAME.fullmatch(self.profile):
            raise NetworkPolicyError(
                "Assignment profile names must match ^[a-z][a-z0-9-]*$"
            )
        if self.workspace_id is not None and self.scope is not PluginReleaseScope.WORKSPACE:
            raise NetworkPolicyError(
                "Only workspace-scope assignments may name a Workspace"
            )
        if self.revision is not None and (
            isinstance(self.revision, bool) or self.revision < 1
        ):
            raise NetworkPolicyError("Assignment revisions must be positive")
        if self.slug is not None and self.slug.strip() == "":
            raise NetworkPolicyError("Assignment slugs must not be blank")

    @property
    def specificity(self) -> int:
        if self.revision is not None:
            return 3
        if self.slug is not None:
            return 2
        if self.scope is not None:
            return 1
        return 0

    def matches(
        self,
        *,
        scope: PluginReleaseScope,
        workspace_id: UUID | None,
        slug: str,
        revision: int,
    ) -> bool:
        if self.scope is not None and self.scope is not scope:
            return False
        if (
            self.workspace_id is not None
            and workspace_id is not None
            and self.workspace_id != workspace_id
        ):
            return False
        if self.slug is not None and self.slug != slug:
            return False
        if self.revision is not None and self.revision != revision:
            return False
        return True

    def specificity_key(self) -> tuple[object, ...]:
        return (
            self.plane,
            self.scope,
            None if self.workspace_id is None else self.workspace_id,
            self.slug,
            self.revision,
        )


class NetworkPolicy:
    """The complete deployment-owned network policy across all planes."""

    def __init__(
        self,
        *,
        profiles: Mapping[tuple[NetworkAccessPlane, str], NetworkAccessProfile] | None = None,
        assignments: tuple[NetworkProfileAssignment, ...] = (),
        defaults: Mapping[NetworkAccessPlane, str] | None = None,
    ) -> None:
        self._profiles: dict[
            tuple[NetworkAccessPlane, str], NetworkAccessProfile
        ] = dict(profiles or {})
        for plane in NetworkAccessPlane:
            self._profiles.setdefault((plane, "offline"), built_in_offline_profile(plane))
        self._assignments = tuple(assignments)
        self._defaults: dict[NetworkAccessPlane, str] = {
            plane: "offline" for plane in NetworkAccessPlane
        }
        if defaults:
            for plane, name in defaults.items():
                self._defaults[plane] = name
        self._validate()

    def _validate(self) -> None:
        for (plane, name), profile in self._profiles.items():
            if profile.plane is not plane:
                raise NetworkPolicyError(
                    f"Profile {name!r} belongs to plane {profile.plane.value!r}, "
                    f"not {plane.value!r}"
                )
        for plane, name in self._defaults.items():
            if (plane, name) not in self._profiles:
                raise NetworkPolicyError(
                    f"Plane {plane.value!r} default names unknown profile {name!r}"
                )
        seen: dict[tuple[object, ...], str] = {}
        for assignment in self._assignments:
            profile_key = (assignment.plane, assignment.profile)
            if profile_key not in self._profiles:
                raise NetworkPolicyError(
                    f"Assignment for {assignment.plane.value!r} names unknown "
                    f"profile {assignment.profile!r}"
                )
            key = assignment.specificity_key()
            if key in seen:
                raise NetworkPolicyError(
                    f"Ambiguous network profile assignments for "
                    f"{assignment.plane.value!r}: {seen[key]!r} and "
                    f"{assignment.profile!r} match the same releases"
                )
            seen[key] = assignment.profile

    @property
    def profiles(self) -> tuple[NetworkAccessProfile, ...]:
        return tuple(
            self._profiles[key]
            for key in sorted(self._profiles, key=lambda key: (key[0].value, key[1]))
        )

    @property
    def assignments(self) -> tuple[NetworkProfileAssignment, ...]:
        return self._assignments

    def profile(
        self, plane: NetworkAccessPlane, name: str
    ) -> NetworkAccessProfile | None:
        return self._profiles.get((plane, name))

    def default_profile(self, plane: NetworkAccessPlane) -> NetworkAccessProfile | None:
        name = self._defaults.get(plane)
        if name is None:
            return None
        return self._profiles.get((plane, name))

    def resolve(
        self,
        plane: NetworkAccessPlane,
        *,
        scope: PluginReleaseScope,
        workspace_id: UUID | None,
        slug: str,
        revision: int,
    ) -> NetworkAccessProfile | None:
        """Resolve the most specific assignment, falling back to the plane default."""

        matching: list[NetworkProfileAssignment] = []
        for assignment in self._assignments:
            if assignment.plane is not plane:
                continue
            if assignment.matches(
                scope=scope,
                workspace_id=workspace_id,
                slug=slug,
                revision=revision,
            ):
                matching.append(assignment)
        if matching:
            top_specificity = max(assignment.specificity for assignment in matching)
            top = [
                assignment
                for assignment in matching
                if assignment.specificity == top_specificity
            ]
            distinct_profiles = {assignment.profile for assignment in top}
            if len(distinct_profiles) != 1:
                raise NetworkPolicyError(
                    f"Ambiguous network profile assignments for {plane.value!r}: "
                    f"{sorted(distinct_profiles)}"
                )
            return self._profiles[(plane, top[0].profile)]
        return self.default_profile(plane)


@dataclass(frozen=True, slots=True)
class HttpEgressResolution:
    """The effective HTTP authority for one node invocation, or its denial."""

    profile: NetworkAccessProfile | None
    reason: NetworkRejectionReason | None = None
    origins: tuple[PluginEgressDestination, ...] = ()
    detail: str = ""

    @property
    def allowed(self) -> bool:
        return self.reason is None


def resolve_http_egress_authority(
    policy: NetworkPolicy,
    *,
    scope: PluginReleaseScope,
    workspace_id: UUID | None,
    slug: str,
    revision: int,
    contract: PluginNodeContract,
    config: Mapping[str, object],
) -> HttpEgressResolution:
    """Intersect one node's request with its assigned profile and config.

    This is the single authority the preflight, the defensive runtime
    admission, and the sandbox builder consume. It never performs DNS;
    address-space safety is enforced at the broker boundary.
    """

    profile = policy.resolve(
        NetworkAccessPlane.PLUGIN_EXECUTION,
        scope=scope,
        workspace_id=workspace_id,
        slug=slug,
        revision=revision,
    )
    if profile is None:
        return HttpEgressResolution(
            profile=None,
            reason=NetworkRejectionReason.PROFILE_UNASSIGNED,
            detail="No network profile is defined for this deployment plane.",
        )
    if not profile.grants_http_authority:
        return HttpEgressResolution(
            profile=profile,
            reason=NetworkRejectionReason.PROFILE_DISABLED,
            detail=(
                f"Assigned network profile {profile.name!r} grants no HTTP egress."
            ),
        )

    http_egress = contract.http_egress
    if http_egress is None:
        if profile.mode is NetworkProfileMode.CURATED and profile.allowed_origins:
            return HttpEgressResolution(profile=profile, origins=profile.allowed_origins)
        return HttpEgressResolution(
            profile=profile,
            reason=NetworkRejectionReason.DESTINATION_UNDECLARED,
            detail=(
                "Historical releases without an HTTP egress contract may only "
                "run under a curated compatibility profile."
            ),
        )

    if http_egress.dynamic_destinations:
        if not profile.allows_dynamic_destinations:
            return HttpEgressResolution(
                profile=profile,
                reason=NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED,
                detail=(
                    "Dynamic destinations require an explicit open-public "
                    f"profile assignment; assigned profile is {profile.name!r}."
                ),
            )
        return HttpEgressResolution(
            profile=profile,
            reason=NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED,
            detail=(
                "The deployment has not enabled the open-public broker mode "
                "required to satisfy dynamic destination requests."
            ),
        )

    origins = _extract_configured_origins(http_egress.configured_inputs, config)
    if isinstance(origins, HttpEgressResolution):
        return _with_profile(origins, profile)
    effective = origins
    if profile.https_only and any(
        origin.protocol is not PluginEgressProtocol.HTTPS for origin in effective
    ):
        return HttpEgressResolution(
            profile=profile,
            reason=NetworkRejectionReason.DESTINATION_NOT_ALLOWLISTED,
            detail=(
                "Assigned profile "
                f"{profile.name!r} only allows HTTPS destinations."
            ),
        )
    if profile.mode is NetworkProfileMode.CURATED:
        allowed = set(profile.allowed_origins)
        effective = tuple(origin for origin in effective if origin in allowed)
        if origins and not effective:
            return HttpEgressResolution(
                profile=profile,
                reason=NetworkRejectionReason.DESTINATION_NOT_ALLOWLISTED,
                detail=(
                    "Configured origins are outside the deployment allowlist for "
                    f"profile {profile.name!r}."
                ),
            )
    if not effective:
        return HttpEgressResolution(
            profile=profile,
            reason=NetworkRejectionReason.DESTINATION_UNDECLARED,
            detail=(
                "The node declares no configured destination value for its "
                "HTTP egress contract."
            ),
        )
    if len(effective) > profile.limits.max_origins_per_execution:
        return HttpEgressResolution(
            profile=profile,
            reason=NetworkRejectionReason.ORIGIN_LIMIT_EXCEEDED,
            detail=(
                f"{len(effective)} configured origins exceed the profile limit "
                f"of {profile.limits.max_origins_per_execution}."
            ),
        )
    return HttpEgressResolution(profile=profile, origins=effective)


def _extract_configured_origins(
    configured_inputs: tuple[str, ...],
    config: Mapping[str, object],
) -> tuple[PluginEgressDestination, ...] | HttpEgressResolution:
    origins: set[PluginEgressDestination] = set()
    for field_name in configured_inputs:
        value = config.get(field_name)
        if value is None:
            continue
        try:
            origins.add(PluginEgressDestination.from_config_url(value))
        except ValueError:
            return HttpEgressResolution(
                profile=None,
                reason=NetworkRejectionReason.DESTINATION_UNDECLARED,
                detail=(
                    f"Config field {field_name!r} is not a valid public "
                    "HTTP(S) destination."
                ),
            )
    return tuple(sorted(origins))


def _with_profile(
    resolution: HttpEgressResolution,
    profile: NetworkAccessProfile,
) -> HttpEgressResolution:
    return HttpEgressResolution(
        profile=profile,
        reason=resolution.reason,
        origins=resolution.origins,
        detail=resolution.detail,
    )


def render_effective_network_policy(
    resolution: HttpEgressResolution,
    *,
    plugin_scope: PluginReleaseScope,
    slug: str,
    revision: int,
    node_operator: str,
    configured_fields: tuple[str, ...] = (),
) -> str:
    """Read-only administrator preview of one node's effective authority."""

    profile = resolution.profile
    lines = [
        f"Plugin: {plugin_scope.value}/{slug}@{revision}",
        f"Node: {node_operator}",
    ]
    if configured_fields:
        rendered_fields = ", ".join(f"`{field_name}`" for field_name in configured_fields)
        lines.append(f"Requested: configured fields {rendered_fields}")
    elif profile is not None:
        lines.append("Requested: no HTTP egress contract")
    if profile is not None:
        lines.append(f"Assigned profile: {profile.name}")
        lines.append(f"Profile digest: {profile.policy_digest}")
    if resolution.allowed:
        if resolution.origins:
            lines.append(
                "Effective origins: "
                + ", ".join(
                    f"{origin.protocol.value}://{origin.authority}"
                    for origin in resolution.origins
                )
            )
        else:
            lines.append("Effective origins: none")
        lines.append(
            "Address policy: public only"
            if profile is None or profile.public_address_only
            else "Address policy: public and exact curated RFC1918"
        )
        if profile is not None and profile.ca_bundle is not None:
            lines.append(
                f"TLS trust bundle: sha256:{profile.ca_bundle.sha256}"
            )
        lines.append("Status: runnable")
    else:
        lines.append(f"Status: denied ({resolution.reason.value})")
        lines.append(resolution.detail)
    return "\n".join(lines)


def load_network_policy_manifest(path: Path) -> NetworkPolicy:
    """Load and validate one deployment network policy manifest."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise NetworkPolicyError(f"Network policy manifest is unreadable: {exc}") from exc
    if document.get("schema_version") != 1:
        raise NetworkPolicyError("Network policy manifest schema_version must be 1")

    domain_sets = _load_domain_sets(document.get("domain_sets"))
    profiles: dict[tuple[NetworkAccessPlane, str], NetworkAccessProfile] = {
        (plane, "offline"): built_in_offline_profile(plane)
        for plane in NetworkAccessPlane
    }
    raw_profiles = document.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise NetworkPolicyError("[profiles] must be a table")
    for plane_key, planes in raw_profiles.items():
        plane = _plane_from_key(plane_key)
        if not isinstance(planes, dict):
            raise NetworkPolicyError(f"[profiles.{plane_key}] must be a table")
        for name, raw_profile in planes.items():
            profile = _profile_from_manifest(
                plane=plane,
                name=name,
                raw_profile=raw_profile,
                domain_sets=domain_sets,
            )
            key = (profile.plane, profile.name)
            if key in profiles:
                raise NetworkPolicyError(
                    f"Duplicate network profile {name!r} for plane {plane.value!r}"
                )
            profiles[key] = profile

    defaults: dict[NetworkAccessPlane, str] = {}
    raw_defaults = document.get("defaults", {})
    if not isinstance(raw_defaults, dict):
        raise NetworkPolicyError("[defaults] must be a table")
    for plane_key, name in raw_defaults.items():
        plane = _plane_from_key(plane_key)
        if not isinstance(name, str) or (plane, name) not in profiles:
            raise NetworkPolicyError(
                f"Plane {plane.value!r} default names unknown profile {name!r}"
            )
        defaults[plane] = name

    assignments: list[NetworkProfileAssignment] = []
    raw_assignments = document.get("assignments", [])
    if not isinstance(raw_assignments, list):
        raise NetworkPolicyError("[[assignments]] must be an array of tables")
    for raw_assignment in raw_assignments:
        if not isinstance(raw_assignment, dict):
            raise NetworkPolicyError("Each assignment must be a table")
        assignments.append(
            _assignment_from_manifest(raw_assignment)
        )

    return NetworkPolicy(
        profiles=profiles,
        assignments=tuple(assignments),
        defaults=defaults,
    )


def legacy_network_policy(
    *,
    http_destinations: tuple[PluginEgressDestination, ...] = (),
) -> NetworkPolicy:
    """Translate legacy egress environment settings into a curated profile.

    Only the plugin-execution plane gains authority: historical ``network.egress``
    releases receive the deployment's exact static HTTP origins, preserving
    pre-manifest behavior. All other planes remain offline.
    """

    profiles: dict[tuple[NetworkAccessPlane, str], NetworkAccessProfile] = {}
    defaults: dict[NetworkAccessPlane, str] = {}
    if http_destinations:
        profiles[
            (NetworkAccessPlane.PLUGIN_EXECUTION, "legacy-curated")
        ] = NetworkAccessProfile(
            name="legacy-curated",
            plane=NetworkAccessPlane.PLUGIN_EXECUTION,
            mode=NetworkProfileMode.CURATED,
            https_only=False,
            allowed_origins=http_destinations,
            label="Legacy GRAFY_PLUGIN_HTTP_EGRESS_DESTINATIONS",
            description=(
                "Translated from legacy egress environment variables; migrate to "
                "GRAFY_NETWORK_POLICY_MANIFEST."
            ),
        )
        defaults[NetworkAccessPlane.PLUGIN_EXECUTION] = "legacy-curated"
    return NetworkPolicy(profiles=profiles, defaults=defaults)


def _load_domain_sets(
    raw: object,
) -> dict[str, tuple[PluginEgressDestination, ...]]:
    sets: dict[str, tuple[PluginEgressDestination, ...]] = {
        "python-packages": _DEFAULT_PYTHON_PACKAGE_ORIGINS
    }
    if raw is None:
        return sets
    if not isinstance(raw, dict):
        raise NetworkPolicyError("[domain_sets] must be a table")
    for name, raw_set in raw.items():
        if not isinstance(raw_set, dict) or not isinstance(raw_set.get("origins"), list):
            raise NetworkPolicyError(
                f"Domain set {name!r} must declare an origins array"
            )
        origins = tuple(
            _origin_from_value(origin, context=f"domain set {name!r}")
            for origin in raw_set["origins"]
        )
        if len(origins) != len(set(origins)):
            raise NetworkPolicyError(f"Domain set {name!r} origins must be unique")
        sets[name] = tuple(sorted(origins))
    return sets


def _profile_from_manifest(
    *,
    plane: NetworkAccessPlane,
    name: str,
    raw_profile: object,
    domain_sets: dict[str, tuple[PluginEgressDestination, ...]],
) -> NetworkAccessProfile:
    if not isinstance(raw_profile, dict):
        raise NetworkPolicyError(f"Profile {name!r} must be a table")
    raw_mode = raw_profile.get("mode")
    if not isinstance(raw_mode, str) or raw_mode not in {
        mode.value for mode in PLANE_MODES[plane]
    }:
        raise NetworkPolicyError(
            f"Profile {name!r} mode {raw_mode!r} is invalid for plane {plane.value!r}"
        )
    allowed_origins: set[PluginEgressDestination] = set()
    raw_allowed = raw_profile.get("allowed_origins", [])
    if not isinstance(raw_allowed, list):
        raise NetworkPolicyError(f"Profile {name!r} allowed_origins must be an array")
    for origin in raw_allowed:
        allowed_origins.add(_origin_from_value(origin, context=f"profile {name!r}"))
    raw_domain_sets = raw_profile.get("domain_sets", [])
    if not isinstance(raw_domain_sets, list):
        raise NetworkPolicyError(
            f"Profile {name!r} domain_sets must be an array"
        )
    for domain_set in raw_domain_sets:
        if not isinstance(domain_set, str) or domain_set not in domain_sets:
            raise NetworkPolicyError(
                f"Profile {name!r} references unknown domain set {domain_set!r}"
            )
        allowed_origins.update(domain_sets[domain_set])
    limits = _limits_from_manifest(raw_profile, context=f"profile {name!r}")
    raw_public = raw_profile.get("public_address_only", True)
    raw_https_only = raw_profile.get("https_only", True)
    if not isinstance(raw_public, bool) or not isinstance(raw_https_only, bool):
        raise NetworkPolicyError(
            f"Profile {name!r} address flags must be booleans"
        )
    raw_ca_bundle_path = raw_profile.get("ca_bundle_path")
    if raw_ca_bundle_path is not None and not isinstance(raw_ca_bundle_path, str):
        raise NetworkPolicyError(
            f"Profile {name!r} ca_bundle_path must be a string"
        )
    ca_bundle = (
        None
        if raw_ca_bundle_path is None
        else NetworkCaBundle.load(Path(raw_ca_bundle_path))
    )
    return NetworkAccessProfile(
        name=name,
        plane=plane,
        mode=NetworkProfileMode(raw_mode),
        public_address_only=raw_public,
        https_only=raw_https_only,
        allowed_origins=tuple(sorted(allowed_origins)),
        ca_bundle=ca_bundle,
        limits=limits,
        label=_optional_str(raw_profile.get("label"), f"profile {name!r} label"),
        description=_optional_str(
            raw_profile.get("description"), f"profile {name!r} description"
        ),
    )


def _limits_from_manifest(raw_profile: Mapping[str, object], *, context: str) -> NetworkProfileLimits:
    known = {
        "max_origins_per_execution",
        "connection_limit",
        "max_header_bytes",
        "max_request_bytes",
        "max_response_bytes",
        "connect_timeout_seconds",
        "idle_timeout_seconds",
    }
    values: dict[str, int] = {}
    for name in known:
        if name in raw_profile:
            values[name] = raw_profile[name]
    raw_limits = raw_profile.get("limits")
    if raw_limits is not None:
        if not isinstance(raw_limits, dict):
            raise NetworkPolicyError(f"{context} limits must be a table")
        for name, value in raw_limits.items():
            if name not in known:
                raise NetworkPolicyError(
                    f"{context} declares unknown limits: {sorted({name})}"
                )
            if name in values:
                raise NetworkPolicyError(
                    f"{context} declares limit {name!r} both in the profile "
                    "table and its limits table"
                )
            values[name] = value
    defaults = NetworkProfileLimits()
    return NetworkProfileLimits(
        max_origins_per_execution=_manifest_int(
            values, "max_origins_per_execution", defaults.max_origins_per_execution, context
        ),
        connection_limit=_manifest_int(
            values, "connection_limit", defaults.connection_limit, context
        ),
        max_header_bytes=_manifest_int(
            values, "max_header_bytes", defaults.max_header_bytes, context
        ),
        max_request_bytes=_manifest_int(
            values, "max_request_bytes", defaults.max_request_bytes, context
        ),
        max_response_bytes=_manifest_int(
            values, "max_response_bytes", defaults.max_response_bytes, context
        ),
        connect_timeout_seconds=_manifest_int(
            values, "connect_timeout_seconds", defaults.connect_timeout_seconds, context
        ),
        idle_timeout_seconds=_manifest_int(
            values, "idle_timeout_seconds", defaults.idle_timeout_seconds, context
        ),
    )


def _assignment_from_manifest(raw: Mapping[str, object]) -> NetworkProfileAssignment:
    raw_plane = raw.get("plane")
    if not isinstance(raw_plane, str):
        raise NetworkPolicyError("Assignment requires a plane")
    plane = _plane_from_key(raw_plane)
    raw_profile = raw.get("profile")
    if not isinstance(raw_profile, str):
        raise NetworkPolicyError("Assignment requires a profile name")
    scope: PluginReleaseScope | None = None
    raw_scope = raw.get("scope")
    if raw_scope is not None:
        if raw_scope not in {scope.value for scope in PluginReleaseScope}:
            raise NetworkPolicyError(
                f"Assignment scope {raw_scope!r} must be system or workspace"
            )
        scope = PluginReleaseScope(raw_scope)
    workspace_id: UUID | None = None
    raw_workspace = raw.get("workspace_id")
    if raw_workspace is not None:
        try:
            workspace_id = UUID(str(raw_workspace))
        except ValueError as exc:
            raise NetworkPolicyError(
                "Assignment workspace_id must be a UUID"
            ) from exc
    raw_slug = raw.get("slug")
    slug: str | None = None
    if raw_slug is not None:
        if not isinstance(raw_slug, str) or raw_slug.strip() == "":
            raise NetworkPolicyError("Assignment slug must be a non-empty string")
        slug = raw_slug
    raw_revision = raw.get("revision")
    revision: int | None = None
    if raw_revision is not None:
        if (
            isinstance(raw_revision, bool)
            or not isinstance(raw_revision, int)
            or raw_revision < 1
        ):
            raise NetworkPolicyError("Assignment revision must be a positive integer")
        revision = raw_revision
    return NetworkProfileAssignment(
        plane=plane,
        profile=raw_profile,
        scope=scope,
        workspace_id=workspace_id,
        slug=slug,
        revision=revision,
    )


def _origin_from_value(value: object, *, context: str) -> PluginEgressDestination:
    if not isinstance(value, str):
        raise NetworkPolicyError(f"{context} origins must be strings")
    try:
        return PluginEgressDestination.parse(value)
    except ValueError as exc:
        raise NetworkPolicyError(f"{context} origin {value!r} is invalid: {exc}") from exc


def _plane_from_key(value: object) -> NetworkAccessPlane:
    if not isinstance(value, str):
        raise NetworkPolicyError(f"Unknown network plane {value!r}")
    normalized = value.replace("_", "-")
    try:
        return NetworkAccessPlane(normalized)
    except ValueError as exc:
        raise NetworkPolicyError(f"Unknown network plane {value!r}") from exc


def _manifest_int(
    values: Mapping[str, object],
    name: str,
    default: int,
    context: str,
) -> int:
    if name not in values:
        return default
    value = values[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise NetworkPolicyError(f"{context} limit {name!r} must be an integer")
    return value


def _optional_str(value: object, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NetworkPolicyError(f"{context} must be a string")
    return value


def _check_range(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not minimum <= value <= maximum:
        raise NetworkPolicyError(
            f"Network profile limit {name!r} must be between {minimum} and {maximum}"
        )


__all__ = [
    "HttpEgressResolution",
    "NetworkAccessPlane",
    "NetworkAccessProfile",
    "NetworkCaBundle",
    "NetworkPolicy",
    "NetworkPolicyError",
    "NetworkProfileAssignment",
    "NetworkProfileLimits",
    "NetworkProfileMode",
    "NetworkRejectionReason",
    "built_in_offline_profile",
    "legacy_network_policy",
    "load_network_policy_manifest",
    "render_effective_network_policy",
    "resolve_http_egress_authority",
]

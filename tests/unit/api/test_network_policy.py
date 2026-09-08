"""Deployment-owned network access profiles, assignments, and resolution."""

from pathlib import Path
import re
from uuid import UUID

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.plugin_releases import (
    PluginNodeContract,
    PluginNodeHttpEgressContract,
)
from grafy_api.plugins.runtime.network_policy import (
    NetworkAccessPlane,
    NetworkAccessProfile,
    NetworkCaBundle,
    NetworkPolicy,
    NetworkPolicyError,
    NetworkProfileAssignment,
    NetworkProfileLimits,
    NetworkProfileMode,
    NetworkRejectionReason,
    HttpEgressResolution,
    built_in_offline_profile,
    legacy_network_policy,
    load_network_policy_manifest,
    render_effective_network_policy,
    resolve_http_egress_authority,
)
from grafy_api.plugins.runtime.egress import (
    PluginEgressDestination,
    PluginEgressProtocol,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000993")
SLUG = "external.llm"


def _e2e_ca_bytes() -> bytes:
    return (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "e2e"
        / "tls"
        / "ca.crt"
    ).read_bytes()


def _write_manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "network-policy.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _contract(
    configured: tuple[str, ...] = (),
    *,
    dynamic: bool = False,
) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id="llm.openai_compatible.chat_completion",
        operator_version=1,
        title="Chat",
        description="Calls a provider.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(),
        required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
        http_egress=(
            None
            if not configured and not dynamic
            else PluginNodeHttpEgressContract(
                configured_inputs=configured,
                dynamic_destinations=dynamic,
            )
        ),
    )


def _resolve(
    policy: NetworkPolicy,
    contract: PluginNodeContract,
    config: dict[str, object],
    *,
    scope: PluginReleaseScope = PluginReleaseScope.SYSTEM,
    slug: str = SLUG,
    revision: int = 1,
) -> HttpEgressResolution:
    return resolve_http_egress_authority(
        policy,
        scope=scope,
        workspace_id=None if scope is PluginReleaseScope.SYSTEM else WORKSPACE_ID,
        slug=slug,
        revision=revision,
        contract=contract,
        config=config,
    )


def _public_profile(
    *,
    name: str = "configured-public",
    origins: tuple[str, ...] = (),
    https_only: bool = True,
    max_origins: int = 8,
    mode: NetworkProfileMode = NetworkProfileMode.CONFIGURED_PUBLIC,
) -> NetworkAccessProfile:
    return NetworkAccessProfile(
        name=name,
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=mode,
        https_only=https_only,
        allowed_origins=tuple(
            PluginEgressDestination.parse(origin) for origin in origins
        ),
        limits=NetworkProfileLimits(
            max_origins_per_execution=max_origins
        ),
    )


def _policy(
    profile: NetworkAccessProfile,
    *,
    slug: str | None = None,
    revision: int | None = None,
) -> NetworkPolicy:
    return NetworkPolicy(
        profiles={(profile.plane, profile.name): profile},
        assignments=(
            NetworkProfileAssignment(
                plane=profile.plane,
                profile=profile.name,
                scope=PluginReleaseScope.SYSTEM,
                slug=slug,
                revision=revision,
            ),
        ),
    )


def test_development_manifest_allows_notarius_configured_public_egress() -> None:
    policy = load_network_policy_manifest(
        Path(__file__).resolve().parents[3] / "network-policy.toml"
    )
    contract = _contract(("base_url",))
    config = {"base_url": "https://api.openai.com/v1"}

    resolution = resolve_http_egress_authority(
        policy,
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=UUID("5ff0b54e-a3fd-4904-8d58-ee157e419b3a"),
        slug="external.notarius",
        revision=1,
        contract=contract,
        config=config,
    )
    unrelated_workspace = resolve_http_egress_authority(
        policy,
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=WORKSPACE_ID,
        slug="external.notarius",
        revision=1,
        contract=contract,
        config=config,
    )

    assert resolution.allowed, resolution.detail
    assert resolution.profile is not None
    assert resolution.profile.mode is NetworkProfileMode.CONFIGURED_PUBLIC
    assert resolution.origins == (
        PluginEgressDestination.parse("https://api.openai.com:443"),
    )
    assert unrelated_workspace.reason is NetworkRejectionReason.PROFILE_DISABLED


def test_manifest_parses_profiles_assignments_and_defaults(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."plugin-execution".llm-public]
mode = "configured-public"
allowed_origins = ["https://api.openai.com:443"]
label = "LLM providers"

[profiles."agent-authoring".deps]
mode = "dependencies"
domain_sets = ["python-packages"]

[defaults]
"plugin-execution" = "offline"
"agent-authoring" = "offline"

[[assignments]]
plane = "plugin-execution"
scope = "system"
slug = "external.llm"
profile = "llm-public"

[[assignments]]
plane = "agent-authoring"
profile = "deps"
""",
    )
    policy = load_network_policy_manifest(path)

    profile = policy.profile(
        NetworkAccessPlane.PLUGIN_EXECUTION, "llm-public"
    )
    assert profile is not None
    assert len(profile.allowed_origins) == 1

    deps = policy.profile(NetworkAccessPlane.AGENT_AUTHORING, "deps")
    assert deps is not None
    assert {origin.host for origin in deps.allowed_origins} == {
        "pypi.org",
        "files.pythonhosted.org",
    }

    resolved = policy.resolve(
        NetworkAccessPlane.PLUGIN_EXECUTION,
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
        slug="external.llm",
        revision=1,
    )
    assert resolved is profile
    default = policy.resolve(
        NetworkAccessPlane.PLUGIN_EXECUTION,
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
        slug="other",
        revision=1,
    )
    assert default is not None and default.mode is NetworkProfileMode.DISABLED
    assert len(policy.assignments) == 2


def test_manifest_requires_schema_version_one(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, 'schema_version = 2\n')
    with pytest.raises(NetworkPolicyError, match="schema_version must be 1"):
        load_network_policy_manifest(path)


def test_manifest_rejects_invalid_mode_for_plane(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."publication".nope]
mode = "configured-public"
""",
    )
    with pytest.raises(NetworkPolicyError, match="invalid for plane"):
        load_network_policy_manifest(path)


def test_manifest_rejects_duplicate_profile(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."plugin-execution".offline]
mode = "curated"
allowed_origins = ["https://example.com:443"]
""",
    )
    with pytest.raises(NetworkPolicyError, match="Duplicate network profile"):
        load_network_policy_manifest(path)


def test_manifest_rejects_unknown_default_profile(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        """
schema_version = 1

[defaults]
"plugin-execution" = "missing"
""",
    )
    with pytest.raises(NetworkPolicyError, match="unknown profile"):
        load_network_policy_manifest(path)


def test_manifest_rejects_unknown_domain_set_and_ip_origins(
    tmp_path: Path,
) -> None:
    unknown_set = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."agent-authoring".deps]
mode = "dependencies"
domain_sets = ["nope"]
""",
    )
    with pytest.raises(NetworkPolicyError, match="unknown domain set"):
        load_network_policy_manifest(unknown_set)

    ip_origin = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."plugin-execution".bad]
mode = "curated"
allowed_origins = ["https://127.0.0.1:443"]
""",
    )
    with pytest.raises(NetworkPolicyError, match="invalid"):
        load_network_policy_manifest(ip_origin)


def test_manifest_accepts_top_level_and_nested_limits(tmp_path: Path) -> None:
    top_level = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."plugin-execution".limited]
mode = "configured-public"
max_origins_per_execution = 2
connect_timeout_seconds = 5
""",
    )
    profile = load_network_policy_manifest(top_level).profile(
        NetworkAccessPlane.PLUGIN_EXECUTION, "limited"
    )
    assert profile is not None
    assert profile.limits.max_origins_per_execution == 2
    assert profile.limits.connect_timeout_seconds == 5

    conflicting = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."plugin-execution".limited]
mode = "configured-public"
max_origins_per_execution = 2

[profiles."plugin-execution".limited.limits]
max_origins_per_execution = 3
""",
    )
    with pytest.raises(NetworkPolicyError, match="both"):
        load_network_policy_manifest(conflicting)


def test_profile_digest_is_stable_and_sensitive_to_authority() -> None:
    origins = ("https://api.example.com:443",)
    profile = _public_profile(origins=origins)
    assert profile.policy_digest == profile.policy_digest

    relabeled = NetworkAccessProfile(
        name=profile.name,
        plane=profile.plane,
        mode=profile.mode,
        https_only=profile.https_only,
        allowed_origins=profile.allowed_origins,
        limits=profile.limits,
        label="A different label",
        description="Changed prose",
    )
    assert relabeled.policy_digest == profile.policy_digest

    widened = _public_profile(
        origins=("https://api.example.com:443", "https://other.example.com:443")
    )
    assert widened.policy_digest != profile.policy_digest
    assert (
        _public_profile(origins=origins, https_only=False).policy_digest
        != profile.policy_digest
    )


def test_builtin_offline_profile_exists_on_every_plane() -> None:
    policy = NetworkPolicy()
    for plane in NetworkAccessPlane:
        offline = policy.default_profile(plane)
        assert offline is not None
        assert offline.mode in {
            NetworkProfileMode.DISABLED,
            NetworkProfileMode.OFFLINE,
        }
        assert offline.grants_http_authority is False
        assert (
            policy.profile(plane, "offline") == built_in_offline_profile(plane)
        )


def test_resolution_precedence_is_revision_over_slug_over_scope_over_default() -> None:
    execution = NetworkAccessPlane.PLUGIN_EXECUTION
    exact = _public_profile(name="exact")
    family = _public_profile(name="family")
    scoped = _public_profile(name="scoped")
    default = _public_profile(name="default")
    policy = NetworkPolicy(
        profiles={
            (execution, profile.name): profile
            for profile in (exact, family, scoped, default)
        },
        assignments=(
            NetworkProfileAssignment(
                plane=execution, profile="exact", scope=PluginReleaseScope.SYSTEM,
                slug=SLUG, revision=3,
            ),
            NetworkProfileAssignment(
                plane=execution, profile="family", scope=PluginReleaseScope.SYSTEM,
                slug=SLUG,
            ),
            NetworkProfileAssignment(
                plane=execution, profile="scoped", scope=PluginReleaseScope.SYSTEM,
            ),
        ),
        defaults={execution: "default"},
    )

    resolved = policy.resolve(
        execution,
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
        slug=SLUG,
        revision=3,
    )
    assert resolved is exact
    resolved = policy.resolve(
        execution,
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
        slug=SLUG,
        revision=1,
    )
    assert resolved is family
    resolved = policy.resolve(
        execution,
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
        slug="other",
        revision=1,
    )
    assert resolved is scoped
    resolved = policy.resolve(
        execution,
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=WORKSPACE_ID,
        slug=SLUG,
        revision=1,
    )
    assert resolved is default


def test_ambiguous_assignments_are_rejected() -> None:
    execution = NetworkAccessPlane.PLUGIN_EXECUTION
    with pytest.raises(NetworkPolicyError, match="Ambiguous"):
        NetworkPolicy(
            profiles={
                (execution, "one"): _public_profile(name="one"),
                (execution, "two"): _public_profile(name="two"),
            },
            assignments=(
                NetworkProfileAssignment(
                    plane=execution, profile="one", scope=PluginReleaseScope.SYSTEM,
                    slug=SLUG,
                ),
                NetworkProfileAssignment(
                    plane=execution, profile="two", scope=PluginReleaseScope.SYSTEM,
                    slug=SLUG,
                ),
            ),
        )


def test_workspace_assignments_require_workspace_scope() -> None:
    with pytest.raises(NetworkPolicyError, match="workspace"):
        NetworkProfileAssignment(
            plane=NetworkAccessPlane.PLUGIN_EXECUTION,
            profile="offline",
            workspace_id=WORKSPACE_ID,
        )


def test_curated_profile_may_allow_rfc1918_for_exact_origins() -> None:
    destination = PluginEgressDestination.parse(
        "https://openai-e2e:8443"
    )

    profile = NetworkAccessProfile(
        name="e2e-provider",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.CURATED,
        public_address_only=False,
        allowed_origins=(destination,),
    )

    assert profile.public_address_only is False
    assert profile.allowed_origins == (destination,)


@pytest.mark.parametrize(
    "mode, origins",
    [
        (NetworkProfileMode.CONFIGURED_PUBLIC, ("https://openai-e2e:8443",)),
        (NetworkProfileMode.OPEN_PUBLIC, ("https://openai-e2e:8443",)),
        (NetworkProfileMode.CURATED, ()),
    ],
)
def test_non_public_address_space_requires_exact_curated_origins(
    mode: NetworkProfileMode,
    origins: tuple[str, ...],
) -> None:
    with pytest.raises(NetworkPolicyError, match="exact curated"):
        NetworkAccessProfile(
            name="lan",
            plane=NetworkAccessPlane.PLUGIN_EXECUTION,
            mode=mode,
            public_address_only=False,
            allowed_origins=tuple(
                PluginEgressDestination.parse(origin) for origin in origins
            ),
        )


def test_exact_curated_profile_owns_ca_bundle_by_content(
    tmp_path: Path,
) -> None:
    ca_path = tmp_path / "provider-ca.crt"
    ca_path.write_bytes(_e2e_ca_bytes())
    destination = PluginEgressDestination.parse("https://openai-e2e:8443")

    bundle = NetworkCaBundle.load(ca_path)
    profile = NetworkAccessProfile(
        name="e2e-provider",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.CURATED,
        public_address_only=False,
        allowed_origins=(destination,),
        ca_bundle=bundle,
    )

    assert profile.ca_bundle is not None
    assert profile.ca_bundle.path == ca_path
    assert profile.ca_bundle.sha256 == (
        "269d1be5ad14cbc96a0c668deb44776d47098beacf44c5bec07b2cb44191ecb9"
    )

    with pytest.raises(NetworkPolicyError, match="exact curated"):
        NetworkAccessProfile(
            name="configured-public",
            plane=NetworkAccessPlane.PLUGIN_EXECUTION,
            mode=NetworkProfileMode.CONFIGURED_PUBLIC,
            allowed_origins=(destination,),
            ca_bundle=bundle,
        )


@pytest.mark.parametrize(
    "suffix",
    [
        b"-----BEGIN PRIVATE KEY-----\nc2VjcmV0\n-----END PRIVATE KEY-----\n",
        b"-----BEGIN PUBLIC KEY-----\ndW5rbm93bg==\n-----END PUBLIC KEY-----\n",
        b"unexpected trailing content\n",
        b"-----BEGIN CERTIFICATE-----\nbWFsZm9ybWVk\n",
    ],
)
def test_ca_bundle_rejects_any_content_outside_certificates(
    tmp_path: Path,
    suffix: bytes,
) -> None:
    ca_path = tmp_path / "unsafe-ca.pem"
    ca_path.write_bytes(_e2e_ca_bytes() + suffix)

    with pytest.raises(NetworkPolicyError, match="certificate PEM blocks only"):
        NetworkCaBundle.load(ca_path)


def test_ca_bundle_accepts_multiple_certificates_and_whitespace(
    tmp_path: Path,
) -> None:
    ca_path = tmp_path / "ca-chain.pem"
    ca_path.write_bytes(b"\n\t" + _e2e_ca_bytes() + b"\n" + _e2e_ca_bytes())

    bundle = NetworkCaBundle.load(ca_path)

    assert bundle.content.count(b"-----BEGIN CERTIFICATE-----") == 2


def test_manifest_loads_ca_bundle_only_for_exact_curated_profile(
    tmp_path: Path,
) -> None:
    ca_path = tmp_path / "provider-ca.crt"
    ca_path.write_bytes(_e2e_ca_bytes())
    manifest = _write_manifest(
        tmp_path,
        f'''\
schema_version = 1

[profiles.plugin-execution.e2e-provider]
mode = "curated"
public_address_only = false
allowed_origins = ["https://openai-e2e:8443"]
ca_bundle_path = "{ca_path}"
''',
    )

    profile = load_network_policy_manifest(manifest).profile(
        NetworkAccessPlane.PLUGIN_EXECUTION,
        "e2e-provider",
    )

    assert profile is not None
    assert profile.ca_bundle is not None
    assert profile.ca_bundle.path == ca_path

    resolution = _resolve(
        _policy(profile, slug=SLUG),
        _contract(("base_url",)),
        {"base_url": "https://openai-e2e:8443/v1"},
    )
    rendered = render_effective_network_policy(
        resolution,
        plugin_scope=PluginReleaseScope.SYSTEM,
        slug=SLUG,
        revision=1,
        node_operator="llm.openai_compatible.chat_completion@1",
    )
    assert "Address policy: public and exact curated RFC1918" in rendered
    assert f"TLS trust bundle: sha256:{profile.ca_bundle.sha256}" in rendered
    assert str(ca_path) not in rendered


def test_legacy_translation_keeps_historical_authority() -> None:
    destination = PluginEgressDestination.parse("https://api.example.com:443")
    policy = legacy_network_policy(http_destinations=(destination,))

    profile = policy.default_profile(NetworkAccessPlane.PLUGIN_EXECUTION)
    assert profile is not None
    assert profile.mode is NetworkProfileMode.CURATED
    assert profile.allowed_origins == (destination,)
    assert (
        policy.default_profile(NetworkAccessPlane.PUBLICATION) is not None
        and policy.default_profile(NetworkAccessPlane.PUBLICATION).grants_http_authority
        is False
    )

    empty = legacy_network_policy()
    default = empty.default_profile(NetworkAccessPlane.PLUGIN_EXECUTION)
    assert default is not None
    assert default.mode is NetworkProfileMode.DISABLED


def test_historical_node_without_contract_runs_only_under_curated() -> None:
    curated = _public_profile(
        name="curated",
        mode=NetworkProfileMode.CURATED,
        origins=("https://api.example.com:443",),
    )
    policy = _policy(curated, slug=SLUG)

    resolution = _resolve(policy, _contract(), {})
    assert resolution.allowed
    assert (
        resolution.origins
        == (PluginEgressDestination.parse("https://api.example.com:443"),)
    )

    disabled = _policy(_public_profile(), slug=SLUG)
    resolution = _resolve(disabled, _contract(), {})
    assert resolution.reason is NetworkRejectionReason.DESTINATION_UNDECLARED


def test_resolver_extracts_and_normalizes_configured_origins() -> None:
    policy = _policy(_public_profile(https_only=False), slug=SLUG)
    contract = _contract(("base_url", "fallback_url"))

    resolution = _resolve(
        policy,
        contract,
        {
            "base_url": "https://API.Example.com/v1?token=secret#frag",
            "fallback_url": "http://Backup.EXAMPLE.com./",
        },
    )
    assert resolution.allowed
    assert resolution.origins == (
        PluginEgressDestination.parse("http://backup.example.com:80"),
        PluginEgressDestination.parse("https://api.example.com:443"),
    )


def test_resolver_rejects_invalid_configured_values() -> None:
    policy = _policy(_public_profile(), slug=SLUG)
    for value in (
        "https://127.0.0.1:443",
        "https://localhost:443",
        "ftp://example.com:21",
        "https://user:pass@example.com:443",
        "not a url",
    ):
        resolution = _resolve(policy, _contract(("base_url",)), {"base_url": value})
        assert resolution.reason is NetworkRejectionReason.DESTINATION_UNDECLARED, value


def test_resolver_missing_config_value_is_undeclared() -> None:
    policy = _policy(_public_profile(), slug=SLUG)
    resolution = _resolve(policy, _contract(("base_url",)), {})
    assert resolution.reason is NetworkRejectionReason.DESTINATION_UNDECLARED


def test_resolver_curated_profile_intersects_configured_origins() -> None:
    curated = _public_profile(
        name="curated",
        mode=NetworkProfileMode.CURATED,
        origins=(
            "https://api.example.com:443",
            "https://backup.example.com:443",
        ),
    )
    policy = _policy(curated, slug=SLUG)

    resolution = _resolve(
        policy,
        _contract(("base_url",)),
        {"base_url": "https://api.example.com/v1"},
    )
    assert resolution.allowed
    assert resolution.origins == (
        PluginEgressDestination.parse("https://api.example.com:443"),
    )

    outside = _resolve(
        policy,
        _contract(("base_url",)),
        {"base_url": "https://intruder.example.com/v1"},
    )
    assert outside.reason is NetworkRejectionReason.DESTINATION_NOT_ALLOWLISTED


def test_resolver_https_only_profile_filters_plain_http() -> None:
    policy = _policy(_public_profile(https_only=True), slug=SLUG)
    resolution = _resolve(
        policy,
        _contract(("base_url",)),
        {"base_url": "http://plain.example.com/"},
    )
    assert resolution.reason is NetworkRejectionReason.DESTINATION_NOT_ALLOWLISTED

    relaxed = _policy(_public_profile(https_only=False), slug=SLUG)
    resolution = _resolve(
        relaxed,
        _contract(("base_url",)),
        {"base_url": "http://plain.example.com/"},
    )
    assert resolution.allowed
    assert resolution.origins[0].protocol is PluginEgressProtocol.HTTP


def test_resolver_denies_dynamic_destinations_until_open_public() -> None:
    for mode in (
        NetworkProfileMode.CONFIGURED_PUBLIC,
        NetworkProfileMode.CURATED,
    ):
        profile = _public_profile(name=f"mode-{mode.value}", mode=mode)
        policy = _policy(profile, slug=SLUG)
        resolution = _resolve(policy, _contract(dynamic=True), {})
        assert resolution.reason is NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED, mode

    open_public = NetworkAccessProfile(
        name="open-public",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.OPEN_PUBLIC,
    )
    policy = _policy(open_public, slug=SLUG)
    resolution = _resolve(policy, _contract(dynamic=True), {})
    assert resolution.reason is NetworkRejectionReason.DYNAMIC_DESTINATION_DENIED
    assert "open-public broker mode" in resolution.detail


def test_resolver_enforces_the_profile_origin_limit() -> None:
    profile = _public_profile(max_origins=1)
    policy = _policy(profile, slug=SLUG)
    resolution = _resolve(
        policy,
        _contract(("first_url", "second_url")),
        {
            "first_url": "https://one.example.com/",
            "second_url": "https://two.example.com/",
        },
    )
    assert resolution.reason is NetworkRejectionReason.ORIGIN_LIMIT_EXCEEDED


def test_documentation_manifest_example_stays_valid(
    tmp_path: Path,
) -> None:
    """The README manifest example is a contract; it must parse here."""

    readme = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "features"
        / "network-access-profiles"
        / "README.md"
    )
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"```toml\n(schema_version = 1.*?)```", text, re.DOTALL)
    assert match is not None, "README lost its manifest example"

    ca_bundle = tmp_path / "internal-provider-ca.pem"
    ca_bundle.write_bytes(_e2e_ca_bytes())
    manifest = tmp_path / "readme-example.toml"
    manifest.write_text(
        match.group(1).replace(
            "/etc/grafy/internal-provider-ca.pem",
            str(ca_bundle),
        ),
        encoding="utf-8",
    )
    policy = load_network_policy_manifest(manifest)

    assert policy.profile(
        NetworkAccessPlane.PLUGIN_EXECUTION, "configured-public"
    ) is not None
    dependencies = policy.profile(
        NetworkAccessPlane.PUBLICATION, "dependencies"
    )
    assert dependencies is not None
    assert {origin.host for origin in dependencies.allowed_origins} == {
        "pypi.org",
        "files.pythonhosted.org",
    }
    default = policy.default_profile(NetworkAccessPlane.PLUGIN_EXECUTION)
    assert default is not None and default.name == "offline"


def test_render_effective_policy_is_read_only_and_complete() -> None:
    policy = _policy(_public_profile(), slug=SLUG)
    resolution = _resolve(
        policy,
        _contract(("base_url",)),
        {"base_url": "https://api.example.com/v1?token=secret"},
    )
    rendered = render_effective_network_policy(
        resolution,
        plugin_scope=PluginReleaseScope.SYSTEM,
        slug=SLUG,
        revision=1,
        node_operator="llm.openai_compatible.chat_completion@1",
        configured_fields=("base_url",),
    )

    assert "system/external.llm@1" in rendered
    assert "Profile digest: " in rendered
    assert "https://api.example.com:443" in rendered
    assert "token=secret" not in rendered
    assert "Status: runnable" in rendered

    denied = _resolve(policy, _contract(dynamic=True), {})
    rendered = render_effective_network_policy(
        denied,
        plugin_scope=PluginReleaseScope.SYSTEM,
        slug=SLUG,
        revision=1,
        node_operator="llm.openai_compatible.chat_completion@1",
    )
    assert "Status: denied (network_dynamic_destination_denied)" in rendered

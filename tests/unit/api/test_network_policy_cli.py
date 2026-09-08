"""Non-mutating validation of the deployment network policy."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from grafy_api import cli
from grafy_api.plugins.runtime.network_policy import (
    NetworkPolicy,
    NetworkPolicyError,
)


def _settings_with(policy: NetworkPolicy, manifest: Path | None) -> SimpleNamespace:
    return SimpleNamespace(
        resolved_network_policy_manifest=manifest,
        resolved_network_policy=policy,
    )


def test_network_policy_validate_prints_profiles_and_assignments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings_with(NetworkPolicy(), None))
    monkeypatch.setattr(sys, "argv", ["grafy", "network-policy", "validate"])

    cli.main()

    output = capsys.readouterr().out
    assert "network policy source: legacy" in output
    assert "name=offline" in output
    assert "network policy OK" in output


def test_network_policy_validate_reads_the_explicit_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "network-policy.toml"
    manifest.write_text(
        """
schema_version = 1

[profiles."plugin-execution".llm-public]
mode = "configured-public"
allowed_origins = ["https://api.example.com:443"]
label = "LLM providers"

[[assignments]]
plane = "plugin-execution"
scope = "system"
slug = "external.llm"
profile = "llm-public"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _settings_with(NetworkPolicy(), manifest),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "network-policy", "validate", "--manifest", str(manifest)],
    )

    cli.main()

    output = capsys.readouterr().out
    assert f"network policy source: {manifest}" in output
    assert "name=llm-public" in output
    assert "origins=1" in output
    assert "slug=external.llm" in output
    assert "network policy OK" in output


def test_network_policy_validate_fails_closed_on_an_invalid_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "network-policy.toml"
    manifest.write_text("schema_version = 2\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _settings_with(NetworkPolicy(), manifest),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "network-policy", "validate", "--manifest", str(manifest)],
    )

    with pytest.raises(NetworkPolicyError, match="schema_version must be 1"):
        cli.main()

    assert "network policy OK" not in capsys.readouterr().out
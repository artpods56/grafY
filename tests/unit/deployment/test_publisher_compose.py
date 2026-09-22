from pathlib import Path
from typing import cast

import yaml


def test_publisher_is_one_shot_profile_and_only_base_service_with_docker_socket() -> (
    None
):
    repository = Path(__file__).resolve().parents[3]
    document = cast(
        dict[str, object],
        yaml.safe_load((repository / "infra/docker/compose.yaml").read_text()),
    )
    services = cast(dict[str, dict[str, object]], document["services"])
    publisher = services["publisher"]
    publisher_volumes = cast(list[str], publisher["volumes"])
    publisher_environment = cast(dict[str, object], publisher["environment"])

    assert publisher["profiles"] == ["publisher"]
    assert publisher["restart"] == "no"
    assert publisher["entrypoint"] == [".venv/bin/grafy"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in publisher_volumes
    assert publisher_environment["GRAFY_PLUGIN_PUBLISHER_SCRATCH_ROOT"] == (
        "${GRAFY_PUBLISHER_SCRATCH_ROOT:-/tmp/grafy-plugin-publisher}"
    )
    assert all(
        "/var/run/docker.sock" not in str(service.get("volumes", []))
        for name, service in services.items()
        if name != "publisher"
    )


def test_publisher_does_not_receive_online_api_secrets() -> None:
    repository = Path(__file__).resolve().parents[3]
    document = cast(
        dict[str, object],
        yaml.safe_load((repository / "infra/docker/compose.yaml").read_text()),
    )
    services = cast(dict[str, dict[str, object]], document["services"])
    environment = cast(dict[str, object], services["publisher"]["environment"])

    assert "GRAFY_OIDC_CLIENT_SECRET" not in environment
    assert "GRAFY_OIDC_AUTH_WRAPPING_KEY" not in environment
    assert "GRAFY_CREDENTIAL_ENCRYPTION_KEY" not in environment
    assert "GRAFY_COMMAND_HMAC_KEY" not in environment


def test_native_runtime_profile_variables_are_exposed_to_api_and_publisher() -> None:
    repository = Path(__file__).resolve().parents[3]
    compose = cast(
        dict[str, object],
        yaml.safe_load((repository / "infra/docker/compose.yaml").read_text()),
    )
    plugin_runtime = cast(
        dict[str, object],
        yaml.safe_load(
            (repository / "infra/docker/compose.plugin-runtime.yaml").read_text()
        ),
    )
    services = cast(dict[str, dict[str, object]], compose["services"])
    runtime_services = cast(dict[str, dict[str, object]], plugin_runtime["services"])

    # A native runtime profile fails closed without both of these, so the
    # publisher and the API must both receive whatever the deployment sets.
    for environment in (
        cast(dict[str, object], services["publisher"]["environment"]),
        cast(dict[str, object], runtime_services["api"]["environment"]),
    ):
        for variable in (
            "GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE",
            "GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE_DIGEST",
        ):
            assert variable in environment, variable
            # A null Compose value imports a configured value and stays unset
            # for deployments that do not run a native profile.
            assert environment[variable] is None, variable

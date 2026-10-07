from pathlib import Path
from typing import cast

import yaml

REPOSITORY = Path(__file__).resolve().parents[3]
PUBLISHED_SERVICES = {
    "migrate": "GRAFY_API_IMAGE",
    "api": "GRAFY_API_IMAGE",
    "web": "GRAFY_WEB_IMAGE",
    "gateway": "GRAFY_GATEWAY_IMAGE",
    "publisher": "GRAFY_PUBLISHER_IMAGE",
}


def _load(path: str) -> dict[str, object]:
    return cast(dict[str, object], yaml.safe_load((REPOSITORY / path).read_text()))


def test_every_built_service_names_an_overridable_image() -> None:
    services = cast(
        dict[str, dict[str, object]], _load("infra/docker/compose.yaml")["services"]
    )

    for name, variable in PUBLISHED_SERVICES.items():
        image = cast(str, services[name]["image"])
        assert image.startswith("${" + variable + ":-grafy-"), name
        assert image.endswith(":local}"), name
        assert "build" in services[name], f"{name} must stay buildable locally"


def test_base_compose_does_not_depend_on_checkout_files_at_runtime() -> None:
    compose = (REPOSITORY / "infra/docker/compose.yaml").read_text()

    assert "nginx.conf" not in compose
    assert "GRAFY_BUILD_DIGEST" not in cast(
        dict[str, object],
        cast(
            dict[str, dict[str, object]], _load("infra/docker/compose.yaml")["services"]
        )["api"]["environment"],
    ), "a Compose environment entry removes the digest baked into release images"


def test_release_api_image_requires_and_bakes_the_build_digest() -> None:
    dockerfile = (REPOSITORY / "infra/docker/api.Dockerfile").read_text()

    release = dockerfile.split("FROM api-plugins AS api-release", maxsplit=1)[1]
    release = release.split("\nFROM ", maxsplit=1)[0]
    assert "ARG GRAFY_BUILD_DIGEST" in release
    assert "[0-9a-f]{64}" in release
    assert "ENV GRAFY_BUILD_DIGEST=$GRAFY_BUILD_DIGEST" in release
    assert dockerfile.rstrip().splitlines()[-3].startswith("FROM source AS api"), (
        "the default build target must stay the plain api image"
    )


def test_gateway_image_bakes_the_checked_in_nginx_config() -> None:
    dockerfile = (REPOSITORY / "infra/docker/gateway.Dockerfile").read_text()

    assert "COPY infra/docker/gateway/nginx.conf /etc/nginx/nginx.conf" in dockerfile


def test_ci_publishes_every_release_image_only_from_green_main() -> None:
    workflow = _load(".github/workflows/ci.yml")
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    publish = jobs["publish-images"]

    assert publish["if"] == (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
    assert set(cast(list[str], publish["needs"])) == set(jobs) - {"publish-images"}
    assert cast(dict[str, str], publish["permissions"])["packages"] == "write"
    matrix = cast(
        list[dict[str, str]],
        cast(dict[str, dict[str, object]], publish["strategy"])["matrix"]["include"],  # type: ignore[index]
    )
    assert {entry["image"] for entry in matrix} == {
        "grafy-api",
        "grafy-publisher",
        "grafy-web",
        "grafy-gateway",
    }
    assert next(e for e in matrix if e["image"] == "grafy-api")["target"] == (
        "api-release"
    )

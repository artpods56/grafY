"""Gateway nginx, Compose agent defaults, and the production deploy script."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import cast

import pytest
import yaml

REPOSITORY = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY / "scripts" / "deploy-production.sh"
NGINX = REPOSITORY / "infra" / "docker" / "gateway" / "nginx.conf"
AGENT_DEFAULTS = (
    "GRAFY_AGENT_DEFAULT_BASE_URL",
    "GRAFY_AGENT_DEFAULT_MODEL",
    "GRAFY_AGENT_DEFAULT_API_KEY",
)

_DOCKER = """\
#!/bin/bash
set -euo pipefail
printf '%s\\n' "$*" >> "${DOCKER_LOG:?}"
if [[ "$1" == "build" ]]; then
	context="${@: -1}"
	printf '%s\\n' "$context" >> "${DOCKER_BUILD_CONTEXTS:?}"
	if [[ ! -d "$context" ]]; then
		printf 'missing build context: %s\\n' "$context" >&2
		exit 1
	fi
	if [[ "${DOCKER_BUILD_FAIL:-}" == "1" ]]; then
		exit 1
	fi
	exit 0
fi
if [[ "$1" == "image" && "$2" == "ls" ]]; then
	cat "${DOCKER_IMAGES:?}"
	exit 0
fi
if [[ "$1" == "rmi" ]]; then
	printf '%s\\n' "$2" >> "${DOCKER_RMI_LOG:?}"
	case "$2" in
		*in-use*) exit 1 ;;
	esac
	exit 0
fi
if [[ "$1" == "compose" ]]; then
	subcommand=""
	for argument in "$@"; do
		case "$argument" in
			config|pull|up|stop|exec|rm|port) subcommand="$argument" ;;
		esac
	done
	case "$subcommand" in
		config)
			printf '%s\\n' \\
				"${GRAFY_API_IMAGE:?}" \\
				"${GRAFY_WEB_IMAGE:?}" \\
				"${GRAFY_GATEWAY_IMAGE:?}" \\
				"${GRAFY_TILER_IMAGE:?}" \\
				> "${DOCKER_CONFIG_IMAGES:?}"
			;;
		port) printf '127.0.0.1:9\\n' ;;
		exec) printf 'PGDMP' ;;
		pull|up|stop|rm) ;;
		*)
			printf 'unexpected compose command: %s\\n' "$*" >&2
			exit 1
			;;
	esac
	exit 0
fi
printf 'unexpected docker command: %s\\n' "$*" >&2
exit 1
"""

_CURL = """\
#!/bin/bash
set -euo pipefail
printf '%s\\n' "$*" >> "${CURL_LOG:?}"
output=""
previous=""
for argument in "$@"; do
	if [[ "$previous" == "--output" ]]; then
		output="$argument"
	fi
	previous="$argument"
done
case "$previous" in
	*raw.githubusercontent.com*)
		[[ -n "$output" ]]
		printf 'name: grafy\\nservices: {}\\n' > "$output"
		;;
	*/api/ready) ;;
	*)
		printf 'unexpected curl url: %s\\n' "$previous" >&2
		exit 1
		;;
esac
"""


def _load(path: str) -> dict[str, object]:
    return cast(dict[str, object], yaml.safe_load((REPOSITORY / path).read_text()))


def _storage_location(text: str) -> str:
    marker = "location ^~ /storage/ {"
    start = text.index(marker)
    depth = 0
    for index, char in enumerate(text[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("storage location block is not closed")


def test_gateway_keeps_an_upstream_forwarded_proto() -> None:
    text = NGINX.read_text()
    storage = _storage_location(text)

    assert "map $http_x_forwarded_proto $grafy_forwarded_proto {" in text
    assert text.index("map $http_x_forwarded_proto") < text.index("\n    server {")
    assert text.count("proxy_set_header X-Forwarded-Proto $grafy_forwarded_proto;") == 3
    assert "proxy_set_header X-Forwarded-Proto $scheme;" not in text
    assert "client_max_body_size 64m;" in storage
    assert "client_body_timeout 600s;" in storage
    assert "proxy_send_timeout 600s;" in storage
    assert "proxy_read_timeout 600s;" in storage
    assert "60s" not in storage
    assert "limit_except PUT {" in storage
    assert 'proxy_set_header Cookie "";' in storage
    assert 'proxy_set_header Authorization "";' in storage
    assert "access_log off;" in storage
    assert (
        '"~^/storage(?<grafy_storage_rest>/workbench-artifacts/[^?]+\\?.+)$"'
        in text
    )


def test_agent_defaults_are_omitted_unless_the_host_set_them() -> None:
    text = (REPOSITORY / "infra/docker/compose.yaml").read_text()
    environment = cast(dict[str, object], _load("infra/docker/compose.yaml")["x-api-environment"])

    for name in AGENT_DEFAULTS:
        assert environment[name] is None
        assert f"\n  {name}:\n" in text
        assert "${" + name not in text

    example = (REPOSITORY / "infra/docker/.env.production.example").read_text()
    for line in example.splitlines():
        if "GRAFY_AGENT_DEFAULT_" in line:
            assert line.lstrip().startswith("#"), line


def test_deploy_guide_matches_the_gateway_and_the_script() -> None:
    guide = (REPOSITORY / "docs/how-to-deploy-production.md").read_text()
    script = SCRIPT.read_text()

    assert "X-Forwarded-Proto" in guide
    assert "Do not bind-mount a" in guide
    assert "600 seconds" in guide
    assert "--build" in guide
    assert "GRAFY_BUILD_REPO_DIR" in guide
    assert "api-release" in guide
    for name in AGENT_DEFAULTS:
        assert name in guide
    assert "dropdb" not in script
    assert "fresh-reset" not in script
    assert "volume rm" not in script


def test_deploy_script_rejects_anything_other_than_one_sha() -> None:
    missing = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    refused = subprocess.run(
        ["bash", str(SCRIPT), "--fresh-reset", "a" * 40],
        capture_output=True,
        text=True,
        check=False,
    )
    bad_sha = subprocess.run(
        ["bash", str(SCRIPT), "main"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert missing.returncode == 2
    assert refused.returncode == 2
    assert bad_sha.returncode == 2
    assert "dropdb" not in refused.stdout
    assert "docker" not in refused.stderr.lower() or "Usage" in refused.stderr


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


def _environment_file(directory: Path) -> Path:
    path = directory / "grafy.env"
    path.write_text(
        "\n".join(
            (
                "GRAFY_OIDC_ISSUER=https://issuer.example",
                "GRAFY_OIDC_CLIENT_ID=grafy",
                "GRAFY_OIDC_AUTH_WRAPPING_KEY=wrapping",
                "GRAFY_CREDENTIAL_ENCRYPTION_KEY=encryption",
                "GRAFY_COMMAND_HMAC_KEY=hmac",
                "GRAFY_TILER_SHARED_KEY=tiler",
                "GRAFY_POSTGRES_PASSWORD=abcdef0123456789",
                "",
            )
        )
    )
    path.chmod(0o600)
    return path


def _fake_tool_env(tmp: Path, images: str) -> dict[str, str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "docker", _DOCKER)
    _write_executable(bin_dir / "curl", _CURL)
    (tmp / "images").write_text(images)
    env = os.environ.copy()
    env.pop("GRAFY_BUILD_REPO_DIR", None)
    env.pop("DOCKER_BUILD_FAIL", None)
    env.update(
        {
            "PATH": os.pathsep.join((str(bin_dir), os.environ["PATH"])),
            "GRAFY_ENV_FILE": str(_environment_file(tmp)),
            "GRAFY_DEPLOY_STATE_DIR": str(tmp / "state"),
            "CURL_LOG": str(tmp / "curl.log"),
            "DOCKER_LOG": str(tmp / "docker.log"),
            "DOCKER_RMI_LOG": str(tmp / "rmi.log"),
            "DOCKER_BUILD_CONTEXTS": str(tmp / "contexts"),
            "DOCKER_CONFIG_IMAGES": str(tmp / "config-images"),
            "DOCKER_IMAGES": str(tmp / "images"),
        }
    )
    for name in ("curl.log", "docker.log", "rmi.log", "contexts"):
        (tmp / name).write_text("")
    return env


def _run_deploy(
    tmp: Path, args: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pull_mode_still_fetches_compose_and_prunes_old_grafy_images(tmp_path: Path) -> None:
    revision = "a" * 40
    previous = "b" * 40
    older = "c" * 40
    state = tmp_path / "state"
    state.mkdir()
    (state / "current-revision").write_text(previous + "\n")
    images = "\n".join(
        (
            f"ghcr.io/artpods56/grafy-api {revision} idcurrent",
            f"ghcr.io/artpods56/grafy-web {revision} idcurrentweb",
            f"ghcr.io/artpods56/grafy-api {previous} idprev",
            f"grafy-tiler {older} idold",
            "postgres 17 idpg",
            "minio latest idminio",
            "mape2 1 idmape",
            "registry 2 idreg",
            "ghcr.io/artpods56/grafy-gateway <none> iddangling",
            "grafy-api in-use-tag idinuse",
            "",
        )
    )
    result = _run_deploy(tmp_path, [revision], _fake_tool_env(tmp_path, images))

    assert result.returncode == 0, result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    docker_log = (tmp_path / "docker.log").read_text()
    removed = (tmp_path / "rmi.log").read_text().splitlines()
    assert f"/{revision}/infra/docker/compose.yaml" in curl_log
    assert f"/{revision}/infra/docker/compose.postgres.yaml" in curl_log
    assert "/api/ready" in curl_log
    assert any(line.endswith(" pull") for line in docker_log.splitlines())
    assert not any(line.startswith("build ") for line in docker_log.splitlines())
    assert (tmp_path / "config-images").read_text().splitlines() == [
        f"ghcr.io/artpods56/grafy-api:{revision}",
        f"ghcr.io/artpods56/grafy-web:{revision}",
        f"ghcr.io/artpods56/grafy-gateway:{revision}",
        f"ghcr.io/artpods56/grafy-tiler:{revision}",
    ]
    assert f"grafy-tiler:{older}" in removed
    assert "iddangling" in removed
    assert "grafy-api:in-use-tag" in removed
    assert f"grafy-api:{revision}" not in removed
    assert f"ghcr.io/artpods56/grafy-api:{revision}" not in removed
    assert f"ghcr.io/artpods56/grafy-api:{previous}" not in removed
    assert "postgres:17" not in removed
    assert "minio:latest" not in removed
    assert "mape2:1" not in removed
    assert "registry:2" not in removed
    assert "Skipped in-use Grafy image: grafy-api:in-use-tag" in result.stderr
    assert (state / "current-revision").read_text() == revision + "\n"
    assert (state / "previous-revision").read_text() == previous + "\n"
    dumps = list(state.glob(f"*-{previous}.dump"))
    assert len(dumps) == 1
    assert stat.S_IMODE(dumps[0].stat().st_mode) == 0o600
    assert "Deployed " + revision in result.stdout


def _commit_checkout(repo: Path) -> str:
    docker_dir = repo / "infra" / "docker"
    docker_dir.mkdir(parents=True)
    (docker_dir / "compose.yaml").write_text("name: from-archive\nservices: {}\n")
    (docker_dir / "compose.postgres.yaml").write_text("services:\n  postgres: {}\n")
    for name in ("gateway.Dockerfile", "api.Dockerfile", "tiler.Dockerfile", "web.Dockerfile"):
        (docker_dir / name).write_text("FROM scratch\n")
    git = ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
    subprocess.run([*git, "init"], check=True, capture_output=True, text=True)
    subprocess.run([*git, "config", "user.email", "deploy@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "Deploy Test"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-m", "release"], check=True, capture_output=True, text=True)
    return subprocess.run(
        [*git, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize("via", ["flag", "env"])
def test_build_mode_archives_the_sha_and_does_not_call_github(tmp_path: Path, via: str) -> None:
    repo = tmp_path / "repo"
    revision = _commit_checkout(repo)
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", revision],
        check=True,
        capture_output=True,
    ).stdout
    digest = hashlib.sha256(archive).hexdigest()
    env = _fake_tool_env(tmp_path, "")
    if via == "flag":
        args = ["--build", str(repo), revision]
    else:
        env["GRAFY_BUILD_REPO_DIR"] = str(repo)
        args = [revision]

    result = _run_deploy(tmp_path, args, env)

    assert result.returncode == 0, result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    docker_log = (tmp_path / "docker.log").read_text()
    assert "raw.githubusercontent.com" not in curl_log
    assert "/api/ready" in curl_log
    assert not any(line.endswith(" pull") for line in docker_log.splitlines())
    assert f"--target api-release --build-arg GRAFY_BUILD_DIGEST={digest}" in docker_log
    assert "--target tiler" in docker_log
    assert f"--tag grafy-gateway:{revision}" in docker_log
    assert f"--tag grafy-web:{revision}" in docker_log
    assert (tmp_path / "config-images").read_text().splitlines() == [
        f"grafy-api:{revision}",
        f"grafy-web:{revision}",
        f"grafy-gateway:{revision}",
        f"grafy-tiler:{revision}",
    ]
    release = tmp_path / "state" / "releases" / revision
    assert (release / "compose.yaml").read_text() == "name: from-archive\nservices: {}\n"
    assert stat.S_IMODE((release / "compose.yaml").stat().st_mode) == 0o600
    contexts = (tmp_path / "contexts").read_text().splitlines()
    assert len(contexts) == 4
    assert len(set(contexts)) == 1
    assert not Path(contexts[0]).exists()


def test_a_failed_build_removes_its_archive_and_leaves_the_release(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    revision = _commit_checkout(repo)
    previous = "b" * 40
    state = tmp_path / "state"
    state.mkdir()
    (state / "current-revision").write_text(previous + "\n")
    env = _fake_tool_env(tmp_path, "")
    env["DOCKER_BUILD_FAIL"] = "1"

    result = _run_deploy(tmp_path, ["--build", str(repo), revision], env)

    assert result.returncode != 0
    contexts = (tmp_path / "contexts").read_text().splitlines()
    assert len(contexts) == 1
    assert not Path(contexts[0]).exists()
    assert (state / "current-revision").read_text() == previous + "\n"
    assert not (state / "previous-revision").exists()
    assert (tmp_path / "curl.log").read_text() == ""
    assert "raw.githubusercontent.com" not in (tmp_path / "docker.log").read_text()

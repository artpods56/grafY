from pathlib import Path
import re


def test_compose_trusts_configured_docker_subnet_for_forwarded_headers() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    env_example = (repository / "infra/docker/.env.production.example").read_text()

    forwarded_allow_ips = re.search(
        r"^\s*FORWARDED_ALLOW_IPS:\s*(\$\{[^}]+\})\s*$",
        compose,
        re.MULTILINE,
    )
    gateway = re.search(
        r"^\s*gateway:\s*(\$\{[^}]+\})\s*$",
        compose,
        re.MULTILINE,
    )
    subnet = re.search(
        r"^\s*-\s+subnet:\s*(\$\{[^}]+\})\s*$",
        compose,
        re.MULTILINE,
    )
    assert forwarded_allow_ips is not None
    assert gateway is not None
    assert subnet is not None
    assert forwarded_allow_ips.group(1) == subnet.group(1)
    assert forwarded_allow_ips.group(1) != gateway.group(1)
    assert gateway.group(1) == "${GRAFY_DOCKER_GATEWAY:-172.30.0.1}"
    assert subnet.group(1) == "${GRAFY_DOCKER_SUBNET:-172.30.0.0/24}"

    env_values = dict(
        line.split("=", maxsplit=1)
        for line in env_example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert env_values["GRAFY_DOCKER_GATEWAY"] == "172.30.0.1"
    assert env_values["GRAFY_DOCKER_SUBNET"] == "172.30.0.0/24"


def test_compose_injects_complete_oidc_configuration_and_requires_keys() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    env_example = (repository / "infra/docker/.env.production.example").read_text()

    required_nonempty = (
        "GRAFY_OIDC_ISSUER",
        "GRAFY_OIDC_CLIENT_ID",
        "GRAFY_OIDC_AUTH_WRAPPING_KEY",
        "GRAFY_CREDENTIAL_ENCRYPTION_KEY",
        "GRAFY_COMMAND_HMAC_KEY",
    )
    for variable in required_nonempty:
        assert re.search(
            rf"^\s*{variable}:\s*\$\{{{variable}:\?[^}}]+\}}\s*$",
            compose,
            re.MULTILINE,
        ), f"{variable} must fail Compose interpolation when unset or empty"

    assert re.search(
        r"^\s*GRAFY_OIDC_CLIENT_SECRET:\s*$",
        compose,
        re.MULTILINE,
    )
    assert (
        "GRAFY_OIDC_ALLOWED_SIGNING_ALGORITHMS: "
        '${GRAFY_OIDC_ALLOWED_SIGNING_ALGORITHMS:-["RS256"]}' in compose
    )
    assert (
        "GRAFY_OIDC_AUTH_WRAPPING_KEY_VERSION: "
        "${GRAFY_OIDC_AUTH_WRAPPING_KEY_VERSION:-1}" in compose
    )

    env_values = dict(
        line.split("=", maxsplit=1)
        for line in env_example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for variable in required_nonempty:
        assert variable in env_values
    assert env_values["GRAFY_OIDC_ALLOWED_SIGNING_ALGORITHMS"] == '["RS256"]'
    assert env_values["GRAFY_OIDC_AUTH_WRAPPING_KEY_VERSION"] == "1"


def test_compose_injects_staged_upload_hard_limit() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    env_example = (repository / "infra/docker/.env.production.example").read_text()

    assert (
        "GRAFY_STAGED_UPLOAD_MAX_BYTES: "
        "${GRAFY_STAGED_UPLOAD_MAX_BYTES:-67108864}" in compose
    )
    assert "GRAFY_STAGED_UPLOAD_MAX_BYTES=67108864" in env_example


def test_compose_data_volume_has_an_explicit_migration_override() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    env_example = (repository / "infra/docker/.env.production.example").read_text()

    assert "name: ${GRAFY_DATA_VOLUME:-grafy-data}" in compose
    assert "GRAFY_DATA_VOLUME=grafy-data" in env_example


def test_nginx_gateway_routes_web_and_api_to_same_origin_upstreams() -> None:
    repository = Path(__file__).parents[3]
    nginx = (repository / "infra/docker/gateway/nginx.conf").read_text()

    assert "upstream grafy_api" in nginx
    assert "server api:8000;" in nginx
    assert "upstream grafy_web" in nginx
    assert "server web:3000;" in nginx
    assert "listen 8080;" in nginx
    assert "client_max_body_size 65m;" in nginx

    root_location = re.search(
        r"location\s+/\s*\{(.*?)\n\s*\}",
        nginx,
        re.DOTALL,
    )
    api_location = re.search(
        r"location\s+/api/\s*\{(.*?)\n\s*\}",
        nginx,
        re.DOTALL,
    )
    assert root_location is not None, "gateway must expose / to Next.js"
    assert api_location is not None, "gateway must expose /api/ to FastAPI"
    assert "proxy_pass http://grafy_web;" in root_location.group(1)
    assert "proxy_pass http://grafy_api/;" in api_location.group(1)
    assert "proxy_buffering off;" in api_location.group(1)


def test_compose_publishes_loopback_gateway_and_keeps_api_web_internal() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    dockerfile = (repository / "infra/docker/api.Dockerfile").read_text()

    assert re.search(r"^  gateway:\s*$", compose, re.MULTILINE)
    assert "./gateway/nginx.conf:/etc/nginx/nginx.conf:ro" in compose
    assert (
        "${GRAFY_BIND_ADDRESS:-127.0.0.1}:${GRAFY_GATEWAY_PORT:-8080}:8080" in compose
    )
    assert 'GRAFY_REQUIRE_SINGLE_API_OWNER: "true"' in compose
    assert 'WEB_CONCURRENCY: "1"' in compose

    # API and web stay on the Compose network; only the gateway publishes
    # host ports.
    api_block = re.search(
        r"^  api:\n(.*?)(?=^  [a-z]|\Z)",
        compose,
        re.MULTILINE | re.DOTALL,
    )
    web_block = re.search(
        r"^  web:\n(.*?)(?=^  [a-z]|\Z)",
        compose,
        re.MULTILINE | re.DOTALL,
    )
    assert api_block is not None
    assert web_block is not None
    assert not re.search(r"^\s+ports:\s*$", api_block.group(1), re.MULTILINE)
    assert not re.search(r"^\s+ports:\s*$", web_block.group(1), re.MULTILINE)
    assert 'expose:\n      - "8000"' in api_block.group(1)
    assert 'expose:\n      - "3000"' in web_block.group(1)

    assert "--workers" not in dockerfile
    assert "grafy_api.main:app" in dockerfile


def test_production_api_does_not_install_isolated_only_plugins_in_process() -> None:
    repository = Path(__file__).parents[3]
    dockerfile = (repository / "infra/docker/api.Dockerfile").read_text()

    production_target = dockerfile.split("FROM source AS api-plugins", maxsplit=1)[1]
    production_target = production_target.split("FROM source AS api", maxsplit=1)[0]
    assert "--package grafy-api" in production_target
    assert "--extra gis" not in production_target
    assert "--extra llm" not in production_target
    assert "--extra ocr" not in production_target
    assert "--extra sql" not in production_target
    assert "gdal-bin" not in production_target


def test_compose_api_healthcheck_uses_dependency_readiness() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    api_block = re.search(
        r"^  api:\n(.*?)(?=^  [a-z]|\Z)",
        compose,
        re.MULTILINE | re.DOTALL,
    )

    assert api_block is not None
    assert "http://127.0.0.1:8000/ready" in api_block.group(1)
    assert "http://127.0.0.1:8000/health" not in api_block.group(1)


def test_nginx_gateway_proxies_presigned_uploads_to_private_minio() -> None:
    repository = Path(__file__).parents[3]
    nginx = (repository / "infra/docker/gateway/nginx.conf").read_text()
    env_example = (repository / "infra/docker/.env.production.example").read_text()

    storage_location = re.search(
        r"location\s+\^~\s+/storage/\s*\{(.*?)\n        \}",
        nginx,
        re.DOTALL,
    )
    assert storage_location is not None, "gateway must expose /storage/ to MinIO"
    body = storage_location.group(1)

    # Only signed PUTs into the artifact bucket reach MinIO.
    assert re.search(r"limit_except\s+PUT\s*\{\s*deny all;\s*\}", body)
    env_values = dict(
        line.split("=", maxsplit=1)
        for line in env_example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    bucket = env_values["GRAFY_STORAGE_BUCKET"]
    uri_map = re.search(
        r"map \$request_uri \$grafy_storage_uri \{(.*?)\n    \}",
        nginx,
        re.DOTALL,
    )
    assert uri_map is not None
    assert f"/{bucket}/" in uri_map.group(1)
    assert 'default "";' in uri_map.group(1)
    assert 'if ($grafy_storage_uri = "") {\n                return 404;' in body

    # SigV4 covers Host (with port) and the raw path/query; both pass unchanged.
    assert "proxy_set_header Host $http_host;" in body
    assert "proxy_pass http://$grafy_storage_upstream$grafy_storage_uri;" in body
    assert "set $grafy_storage_upstream minio:9000;" in body
    assert "resolver 127.0.0.11" in body
    assert 'proxy_set_header Cookie "";' in body

    # Body bounds mirror the staged upload ceiling and stream to MinIO.
    max_bytes = int(env_values["GRAFY_STAGED_UPLOAD_MAX_BYTES"])
    assert max_bytes == 64 * 1024 * 1024
    assert "client_max_body_size 64m;" in body
    assert "proxy_request_buffering off;" in body
    assert "proxy_buffering off;" in body
    assert "client_body_timeout 60s;" in body
    assert "proxy_send_timeout 60s;" in body


def test_compose_wires_signing_endpoint_and_optional_shared_storage() -> None:
    repository = Path(__file__).parents[3]
    compose = (repository / "infra/docker/compose.yaml").read_text()
    shared_storage = (
        repository / "infra/docker/compose.shared-storage.yaml"
    ).read_text()
    env_example = (repository / "infra/docker/.env.production.example").read_text()

    assert (
        "GRAFY_S3_SIGNING_ENDPOINT_URL: ${GRAFY_S3_SIGNING_ENDPOINT_URL:-}" in compose
    )
    assert re.search(r"^GRAFY_S3_SIGNING_ENDPOINT_URL=$", env_example, re.MULTILINE)

    # MinIO stays off the default network and publishes no ports; only the API
    # and gateway join its network.
    assert "minio" not in compose.split("\nservices:", maxsplit=1)[1]
    for service in ("api", "gateway"):
        assert re.search(
            rf"^  {service}:\n    networks:\n      default:\n      shared-storage:\n",
            shared_storage,
            re.MULTILINE,
        )
    assert "ports:" not in shared_storage
    assert "external: true" in shared_storage
    assert "name: ${GRAFY_S3_DOCKER_NETWORK:-shared-storage}" in shared_storage

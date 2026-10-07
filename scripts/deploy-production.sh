#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
	printf 'Usage: %s <40-character Git commit SHA>\n' "$0" >&2
}

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
	usage
	exit 2
fi

revision="$1"
environment_file="${GRAFY_ENV_FILE:-/opt/graphy/.deployment/grafy.env}"
state_dir="${GRAFY_DEPLOY_STATE_DIR:-/opt/graphy/.deployment}"
storage_override="${GRAFY_STORAGE_COMPOSE_OVERRIDE:-}"
github_repository="${GRAFY_GITHUB_REPOSITORY:-artpods56/grafY}"
image_registry="${GRAFY_IMAGE_REGISTRY:-ghcr.io/artpods56}"
release_dir="${state_dir}/releases/${revision}"

if [[ ! -r "$environment_file" ]]; then
	printf 'Cannot read Grafy environment file: %s\n' "$environment_file" >&2
	exit 1
fi

# The images are built and pushed only from main after every CI job passes, so
# a SHA that has images is a reviewed, CI-green commit. The Compose files come
# from the same SHA; the host never needs a checkout.
install -d -m 700 "$state_dir" "$release_dir"
for compose_file in compose.yaml compose.postgres.yaml; do
	if [[ ! -s "${release_dir}/${compose_file}" ]]; then
		curl --fail --silent --show-error --location --retry 3 \
			--output "${release_dir}/${compose_file}.partial" \
			"https://raw.githubusercontent.com/${github_repository}/${revision}/infra/docker/${compose_file}"
		mv "${release_dir}/${compose_file}.partial" "${release_dir}/${compose_file}"
	fi
done

export GRAFY_API_IMAGE="${image_registry}/grafy-api:${revision}"
export GRAFY_WEB_IMAGE="${image_registry}/grafy-web:${revision}"
export GRAFY_GATEWAY_IMAGE="${image_registry}/grafy-gateway:${revision}"
export GRAFY_PUBLISHER_IMAGE="${image_registry}/grafy-publisher:${revision}"

compose=(
	docker compose
	--project-name grafy
	--env-file "$environment_file"
	-f "${release_dir}/compose.yaml"
	-f "${release_dir}/compose.postgres.yaml"
)
if [[ -n "$storage_override" ]]; then
	if [[ ! -r "$storage_override" ]]; then
		printf 'Cannot read storage Compose override: %s\n' "$storage_override" >&2
		exit 1
	fi
	compose+=(-f "$storage_override")
fi

previous_revision="none"
if [[ -r "${state_dir}/current-revision" ]]; then
	recorded_revision="$(<"${state_dir}/current-revision")"
	if [[ "$recorded_revision" =~ ^[0-9a-f]{40}$ ]]; then
		previous_revision="$recorded_revision"
	fi
fi

# Pull everything before stopping traffic so a missing image fails the deploy
# while the previous release is still serving.
"${compose[@]}" config --quiet
"${compose[@]}" pull

"${compose[@]}" up --no-build --pull never --detach --wait postgres
"${compose[@]}" stop gateway api

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${state_dir}/${timestamp}-${previous_revision}.dump"
partial_backup_file="${backup_file}.partial"
"${compose[@]}" exec -T postgres \
	sh -eu -c 'pg_dump --format=custom --no-owner --username "$POSTGRES_USER" "$POSTGRES_DB"' \
	>"$partial_backup_file"
mv "$partial_backup_file" "$backup_file"
chmod 600 "$backup_file"

"${compose[@]}" rm --force --stop migrate
"${compose[@]}" up --no-build --pull never --detach --wait --remove-orphans

gateway_binding="$("${compose[@]}" port gateway 8080)"
curl --fail --silent --show-error "http://${gateway_binding}/api/ready" >/dev/null

printf '%s\n' "$previous_revision" >"${state_dir}/previous-revision"
printf '%s\n' "$revision" >"${state_dir}/current-revision"
printf 'Deployed %s. PostgreSQL backup: %s\n' "$revision" "$backup_file"

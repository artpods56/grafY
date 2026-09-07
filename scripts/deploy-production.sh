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
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
environment_file="${GRAFY_ENV_FILE:-/opt/graphy/.deployment/grafy.env}"
state_dir="${GRAFY_DEPLOY_STATE_DIR:-/opt/graphy/.deployment}"
storage_override="${GRAFY_STORAGE_COMPOSE_OVERRIDE:-}"

if [[ ! -r "$environment_file" ]]; then
	printf 'Cannot read Grafy environment file: %s\n' "$environment_file" >&2
	exit 1
fi

if [[ -n "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]]; then
	printf 'Refusing to deploy from a dirty checkout: %s\n' "$repo_root" >&2
	exit 1
fi

git -C "$repo_root" fetch --prune origin main
git -C "$repo_root" cat-file -e "${revision}^{commit}"
if ! git -C "$repo_root" merge-base --is-ancestor "$revision" origin/main; then
	printf 'Commit is not reachable from origin/main: %s\n' "$revision" >&2
	exit 1
fi

checkout_revision="$(git -C "$repo_root" rev-parse HEAD)"
previous_revision="$checkout_revision"
if [[ -r "${state_dir}/current-revision" ]]; then
	recorded_revision="$(<"${state_dir}/current-revision")"
	if [[ "$recorded_revision" =~ ^[0-9a-f]{40}$ ]] && \
		git -C "$repo_root" cat-file -e "${recorded_revision}^{commit}" 2>/dev/null; then
		previous_revision="$recorded_revision"
	fi
fi
git -C "$repo_root" checkout --detach "$revision"
if command -v sha256sum >/dev/null 2>&1; then
	GRAFY_BUILD_DIGEST="$(git -C "$repo_root" archive "$revision" | sha256sum | cut -d ' ' -f 1)"
else
	GRAFY_BUILD_DIGEST="$(git -C "$repo_root" archive "$revision" | shasum -a 256 | cut -d ' ' -f 1)"
fi
export GRAFY_BUILD_DIGEST

compose=(
	docker compose
	--project-name grafy
	--env-file "$environment_file"
	-f "$repo_root/infra/docker/compose.yaml"
	-f "$repo_root/infra/docker/compose.postgres.yaml"
)
if [[ -n "$storage_override" ]]; then
	if [[ ! -r "$storage_override" ]]; then
		printf 'Cannot read storage Compose override: %s\n' "$storage_override" >&2
		exit 1
	fi
	compose+=(-f "$storage_override")
fi

"${compose[@]}" config --quiet
"${compose[@]}" build

install -d -m 700 "$state_dir"
"${compose[@]}" up --detach --wait postgres
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
"${compose[@]}" up --no-build --detach --wait --remove-orphans

gateway_binding="$("${compose[@]}" port gateway 8080)"
curl --fail --silent --show-error "http://${gateway_binding}/api/ready" >/dev/null

printf '%s\n' "$previous_revision" >"${state_dir}/previous-revision"
printf '%s\n' "$revision" >"${state_dir}/current-revision"
printf 'Deployed %s. PostgreSQL backup: %s\n' "$revision" "$backup_file"

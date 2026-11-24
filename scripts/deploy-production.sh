#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
	printf 'Usage: %s [--build <git-repo-dir>] <40-character Git commit SHA>\n' "$0" >&2
}

# Unused Grafy tags from revisions other than the one just deployed and the one
# it replaced. An in-use image is skipped. postgres, minio, and other
# repositories are not Grafy images and are left alone.
prune_obsolete_grafy_images() {
	local images repo tag id ref
	images="$(docker image ls --format '{{.Repository}} {{.Tag}} {{.ID}}')" || return 1
	while read -r repo tag id; do
		if [[ -z "${repo:-}" ]]; then
			continue
		fi
		case "$repo" in
			grafy-*|"${image_registry}/grafy-"*) ;;
			*) continue ;;
		esac
		if [[ "$tag" == "$revision" ]]; then
			continue
		fi
		if [[ "$previous_revision" =~ ^[0-9a-f]{40}$ && "$tag" == "$previous_revision" ]]; then
			continue
		fi
		if [[ "$tag" == "<none>" ]]; then
			ref="$id"
		else
			ref="${repo}:${tag}"
		fi
		if ! docker rmi "$ref" >/dev/null 2>&1; then
			printf 'Skipped in-use Grafy image: %s\n' "$ref" >&2
		fi
	done <<< "$images"
	return 0
}

build_repo_dir="${GRAFY_BUILD_REPO_DIR:-}"
revision=""
while [[ $# -gt 0 ]]; do
	case "$1" in
		--build)
			if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
				usage
				exit 2
			fi
			build_repo_dir="$2"
			shift 2
			;;
		*)
			if [[ "$1" == -* || -n "$revision" ]]; then
				usage
				exit 2
			fi
			revision="$1"
			shift
			;;
	esac
done

if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
	usage
	exit 2
fi

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

install -d -m 700 "$state_dir" "$release_dir"

if [[ -n "$build_repo_dir" ]]; then
	if [[ ! -e "${build_repo_dir}/.git" ]]; then
		printf 'Not a Git checkout: %s\n' "$build_repo_dir" >&2
		exit 1
	fi
	if ! git -C "$build_repo_dir" cat-file -e "${revision}^{commit}" 2>/dev/null; then
		printf 'Commit %s is not in %s\n' "$revision" "$build_repo_dir" >&2
		exit 1
	fi
	build_dir="$(mktemp -d)"
	trap 'rm -rf "$build_dir"' EXIT
	git -C "$build_repo_dir" archive "$revision" | tar -x -C "$build_dir"
	if command -v sha256sum >/dev/null 2>&1; then
		GRAFY_BUILD_DIGEST="$(
			git -C "$build_repo_dir" archive "$revision" | sha256sum | cut -d ' ' -f 1
		)"
	else
		GRAFY_BUILD_DIGEST="$(
			git -C "$build_repo_dir" archive "$revision" | shasum -a 256 | cut -d ' ' -f 1
		)"
	fi
	export GRAFY_BUILD_DIGEST
	if [[ ! "$GRAFY_BUILD_DIGEST" =~ ^[0-9a-f]{64}$ ]]; then
		printf 'GRAFY_BUILD_DIGEST is not a SHA-256 digest\n' >&2
		exit 1
	fi
	for compose_file in compose.yaml compose.postgres.yaml; do
		install -m 600 \
			"${build_dir}/infra/docker/${compose_file}" \
			"${release_dir}/${compose_file}"
	done
	docker build \
		--file "${build_dir}/infra/docker/gateway.Dockerfile" \
		--tag "grafy-gateway:${revision}" \
		"$build_dir"
	docker build \
		--file "${build_dir}/infra/docker/api.Dockerfile" \
		--target api-release \
		--build-arg "GRAFY_BUILD_DIGEST=${GRAFY_BUILD_DIGEST}" \
		--tag "grafy-api:${revision}" \
		"$build_dir"
	docker build \
		--file "${build_dir}/infra/docker/tiler.Dockerfile" \
		--target tiler \
		--tag "grafy-tiler:${revision}" \
		"$build_dir"
	docker build \
		--file "${build_dir}/infra/docker/web.Dockerfile" \
		--tag "grafy-web:${revision}" \
		"$build_dir"
	export GRAFY_API_IMAGE="grafy-api:${revision}"
	export GRAFY_WEB_IMAGE="grafy-web:${revision}"
	export GRAFY_GATEWAY_IMAGE="grafy-gateway:${revision}"
	export GRAFY_TILER_IMAGE="grafy-tiler:${revision}"
else
	# Images are published from main after CI passes, so a SHA that has images
	# is a reviewed commit. Compose files come from the same SHA. The host
	# does not need a checkout for this path.
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
	export GRAFY_TILER_IMAGE="${image_registry}/grafy-tiler:${revision}"
fi

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

# Pull before stopping traffic so a missing image fails while the previous
# release is still serving. A local build already tagged its images.
"${compose[@]}" config --quiet
if [[ -z "$build_repo_dir" ]]; then
	"${compose[@]}" pull
fi

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
if ! prune_obsolete_grafy_images; then
	printf 'Grafy image prune did not finish; %s is still deployed.\n' "$revision" >&2
fi
printf 'Deployed %s. PostgreSQL backup: %s\n' "$revision" "$backup_file"

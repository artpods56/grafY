#!/usr/bin/env bash
# Worktree setup, run by the t3.json "Setup Worktree" action as
# `bash scripts/setup-worktree.sh`. It installs the locked Python and web
# workspaces and links the main checkout's gitignored .env into this worktree.
# Safe to re-run, and safe to run in the main checkout itself.
set -euo pipefail

worktree="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

project_root="${T3CODE_PROJECT_ROOT:-}"
if [[ -z "${project_root}" ]]; then
    printf 'T3CODE_PROJECT_ROOT is not set. Run this through the t3.json "Setup Worktree" action.\n' >&2
    exit 1
fi

# The env file lives as a real file in the main checkout; worktrees only get a
# symlink to it. Only a symlink is ever replaced, so a real .env is never
# deleted or overwritten, including when this runs in the main checkout.
link_env_file() {
    local source="$1"
    local target="$2"
    if [[ ! -f "${source}" || -L "${source}" ]]; then
        printf 'No regular .env at %s; skipping the link.\n' "${source}" >&2
        return 0
    fi
    if [[ -L "${target}" ]]; then
        rm "${target}"
    elif [[ -e "${target}" ]]; then
        printf 'Skipping .env: %s exists and is not a symlink.\n' "${target}" >&2
        return 0
    fi
    ln -s "${source}" "${target}"
    printf 'Linked %s -> %s\n' "${target}" "${source}"
}

link_env_file "${project_root}/.env" "${worktree}/.env"

# Mirror the Justfile `install` recipe. `just install` keeps one source of
# truth when just is on PATH (the first run in a fresh worktree may not have
# it yet, so fall back to the two raw commands).
cd "${worktree}"
if command -v just >/dev/null 2>&1; then
    just install
else
    uv sync
    npm --prefix apps/web ci
fi

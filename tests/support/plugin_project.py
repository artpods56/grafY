"""Helpers for plugin projects that are copied out of the workspace.

Several sandbox tests copy a plugin directory into a temporary project so they can
build it against a wheel. The workspace declares `grafy-core` as a workspace source
so the families install with the API, and a copy outside the workspace cannot honour
that declaration, so the copied project has to drop it.
"""

import subprocess
from pathlib import Path


def without_workspace_sources(pyproject: Path) -> None:
    """Remove the copied project's `[tool.uv.sources]` table in place."""

    kept: list[str] = []
    skipping = False
    for line in pyproject.read_text().splitlines(keepends=True):
        if line.strip() == "[tool.uv.sources]":
            skipping = True
            continue
        if skipping and line.lstrip().startswith("["):
            skipping = False
        if not skipping:
            kept.append(line)
    pyproject.write_text("".join(kept))


def lock_against_built_core_wheel(repository: Path, project: Path) -> None:
    """Lock the copied project against a `grafy_core` wheel built from this checkout.

    Publication needs a lock in the source archive, and the copy must not reach back
    into the workspace for the library, so the wheel is built locally and offered to
    the resolver with `--find-links`.
    """

    wheels = project / "wheels"
    wheels.mkdir(exist_ok=True)
    for wheel in wheels.glob("grafy_core-*.whl"):
        wheel.unlink()
    subprocess.run(
        (
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(wheels),
            str(repository / "libs" / "core"),
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run(
        ("uv", "lock", "--find-links", "wheels"),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=project,
    )

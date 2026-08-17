from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from grafy_agent_worker.sandbox.guest import program
from grafy_core.source_bundles import read_source_bundle


def _run_guest(
    name: str,
    args: tuple[str, ...],
    *,
    stdin: bytes | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        (sys.executable, "-c", program(name), *args),
        input=stdin,
        capture_output=True,
        cwd=cwd,
        timeout=10,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_program_rejects_invalid_names() -> None:
    with pytest.raises(ValueError, match="invalid sandbox guest program name"):
        program("../secrets")
    with pytest.raises(ValueError, match="invalid sandbox guest program name"):
        program("__init__")


def test_read_text_emits_bytes_and_enforces_limit(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_bytes(b"hello")

    completed = _run_guest("read_text", (str(path), "16"))

    assert completed.returncode == 0
    assert completed.stdout == b"hello"

    oversized = _run_guest("read_text", (str(path), "2"))

    assert oversized.returncode != 0
    assert b"file exceeds 2 bytes" in oversized.stderr


def test_write_text_creates_file_atomically(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "note.txt"

    created = _run_guest(
        "write_text",
        (str(path), "32"),
        stdin=b"first",
    )
    payload = json.loads(created.stdout)

    assert created.returncode == 0
    assert payload == {"created": True, "byte_count": 5}
    assert path.read_bytes() == b"first"

    updated = _run_guest(
        "write_text",
        (str(path), "32"),
        stdin=b"second",
    )
    updated_payload = json.loads(updated.stdout)

    assert updated.returncode == 0
    assert updated_payload == {"created": False, "byte_count": 6}
    assert path.read_bytes() == b"second"

    rejected = _run_guest(
        "write_text",
        (str(path), "3"),
        stdin=b"toolong",
    )
    assert rejected.returncode != 0
    assert b"content exceeds 3 bytes" in rejected.stderr
    assert path.read_bytes() == b"second"


def test_replace_text_requires_exactly_one_match(tmp_path: Path) -> None:
    path = tmp_path / "node.py"
    path.write_text("alpha beta alpha\n", encoding="utf-8")
    request = json.dumps({"expected": "beta", "replacement": "gamma"}).encode()

    patched = _run_guest(
        "replace_text",
        (str(path), "64"),
        stdin=request,
    )
    payload = json.loads(patched.stdout)

    assert patched.returncode == 0
    assert payload["replacements"] == 1
    assert path.read_text(encoding="utf-8") == "alpha gamma alpha\n"

    duplicate = _run_guest(
        "replace_text",
        (str(path), "64"),
        stdin=json.dumps({"expected": "alpha", "replacement": "omega"}).encode(),
    )
    assert duplicate.returncode != 0
    assert b"expected exactly one match but found 2" in duplicate.stderr


def test_fence_exec_rejects_stale_leases_then_runs_the_command(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "fence"
    marker.write_text("current-lease", encoding="utf-8")

    stale = _run_guest(
        "fence_exec",
        (
            str(marker),
            "other-lease",
            sys.executable,
            "-c",
            "print('ran')",
        ),
    )
    assert stale.returncode != 0
    assert b"sandbox lease fence is stale" in stale.stderr

    current = _run_guest(
        "fence_exec",
        (
            str(marker),
            "current-lease",
            sys.executable,
            "-c",
            "print('ran')",
        ),
    )
    assert current.returncode == 0
    assert current.stdout.strip() == b"ran"


def test_write_marker_replaces_the_lease_fence(tmp_path: Path) -> None:
    marker = tmp_path / "control" / "session.fence"

    written = _run_guest("write_marker", (str(marker), "lease-1"))

    assert written.returncode == 0
    assert marker.read_text(encoding="utf-8") == "lease-1"

    replaced = _run_guest("write_marker", (str(marker), "revoked:session"))

    assert replaced.returncode == 0
    assert marker.read_text(encoding="utf-8") == "revoked:session"


def test_archive_reviewable_tree_omits_bytecode_and_virtualenv(tmp_path: Path) -> None:
    root = tmp_path / "node"
    (root / "src" / "__pycache__").mkdir(parents=True)
    (root / "tests" / "__pycache__").mkdir(parents=True)
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".pytest_cache").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='node'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "node.json").write_text("{}\n", encoding="utf-8")
    (root / "src" / "node.py").write_text(
        "def run(inputs): return inputs\n",
        encoding="utf-8",
    )
    (root / "src" / "__pycache__" / "node.cpython-312.pyc").write_bytes(b"\x00pyc")
    (root / "tests" / "test_node.py").write_text(
        "def test_node(): assert True\n",
        encoding="utf-8",
    )
    (root / "tests" / "__pycache__" / "test_node.cpython-312-pytest-8.pyc").write_bytes(
        b"\x00pyc"
    )
    (root / ".venv" / "lib" / "secret.py").write_text("leak = True\n", encoding="utf-8")

    completed = _run_guest("archive_reviewable_tree", (str(root),))

    assert completed.returncode == 0, completed.stderr
    index = read_source_bundle(completed.stdout)
    assert tuple(item.path for item in index.files) == (
        "node.json",
        "pyproject.toml",
        "src/node.py",
        "tests/test_node.py",
        "uv.lock",
    )


def test_copy_runtime_tree_copies_the_node_project(tmp_path: Path) -> None:
    source = tmp_path / "source" / "node"
    target = tmp_path / "runtime" / "node"
    source.mkdir(parents=True)
    (source / "src").mkdir()
    (source / "src" / "node.py").write_text("def run(inputs): return inputs\n")

    completed = _run_guest(
        "copy_runtime_tree",
        (str(source), str(target)),
    )

    assert completed.returncode == 0
    assert (
        target / "src" / "node.py"
    ).read_text() == "def run(inputs): return inputs\n"


def test_runtime_runner_emits_canonical_json_and_redirects_prints(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "node.py").write_text(
        "def run(inputs):\n"
        "    print('leaked')\n"
        "    return {'result': inputs['value'] * 3}\n",
        encoding="utf-8",
    )

    completed = _run_guest(
        "runtime_runner",
        ("1024", "1048576", "256"),
        stdin=b'{"value": 4}',
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"result": 12}
    assert b"leaked" in completed.stderr
    assert b"leaked" not in completed.stdout


def test_runtime_runner_supports_async_run(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "node.py").write_text(
        "async def run(inputs):\n    return {'result': inputs['value'] + 1}\n",
        encoding="utf-8",
    )

    completed = _run_guest(
        "runtime_runner",
        ("1024", "1048576", "256"),
        stdin=b'{"value": 4}',
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"result": 5}


def test_runtime_runner_rejects_oversized_input(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "node.py").write_text(
        "def run(inputs):\n    return inputs\n",
        encoding="utf-8",
    )

    completed = _run_guest(
        "runtime_runner",
        ("8", "1048576", "256"),
        stdin=b'{"value": 4}',
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert b"generated-node input exceeds its limit" in completed.stderr

"""Implementation identity (ADR 0020, issue #194).

The rule under test: deploying a build that did not change a node's code must
not change that node's identity, and changing a module the node imports inside
its own family package must. Each case moves exactly one input and demands the
digest moves, or leaves the closure untouched and demands it does not. No
imports are executed, so no sleeps, no cleanup of ``sys.modules`` — the
throwaway families under ``tmp_path`` are only ever parsed.
"""

import importlib
import re
import shutil
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest

from grafy_core.kernel.implementation_identity import (
    EXECUTION_EPOCH,
    RegistryImplementationDigests,
    family_project_name,
    implementation_digest,
    import_closure,
    import_closure_digest,
    locked_dependency_versions,
)
from tests.unit.kernel.builders import make_node

REPO_ROOT = Path(__file__).resolve().parents[3]
UV_LOCK = REPO_ROOT / "uv.lock"

HEX_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def _fam(label: str) -> str:
    return f"fam_{label}_{uuid.uuid4().hex}"


def _syspath_prepend(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    # pytest's own syspath_prepend is unannotated; setattr is typed.
    monkeypatch.setattr(sys, "path", [path, *sys.path])


def _make_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    files: Mapping[str, str],
    *,
    parent: Path | None = None,
) -> Path:
    """Write a throwaway family package and put its parent on ``sys.path``."""
    root = tmp_path if parent is None else parent
    for relative, content in files.items():
        path = root / name / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _syspath_prepend(monkeypatch, str(root))
    importlib.invalidate_caches()
    return root / name


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _closure_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str]:
    """A family whose main module reaches everything through every import form.

    Returns ``(family, main_module, other_family)``.
    """
    name = _fam("closure")
    other = _fam("other")
    _make_family(
        tmp_path,
        monkeypatch,
        other,
        {
            "__init__.py": "",
            "geometry.py": "GEOMETRY = 1\n",
        },
    )
    files = {
        "__init__.py": "",
        "main.py": (
            "import json\n"  # stdlib: ignored
            "import pydantic\n"  # third party: ignored
            "import grafy_core.artifacts\n"  # core: outside the closure
            f"import {other}.geometry\n"  # another family: ignored
            f"from {name}.helpers import util_a\n"  # direct
            f"from {name}.deep.chain import leaf_fn\n"  # transitive + ancestor
            "from .sibling import thing\n"  # relative, level 1
            "from . import lazy_host\n"  # relative, submodule name
            f"from {name} import submodule_host\n"  # from P import <module>
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            f"    from {name}.typing_only import TypingThing\n"
            "def _late():\n"
            f"    from {name}.late import arrive\n"
            "    return arrive\n"
            f"from {name}.cycle_a import first\n"  # import cycle
        ),
        "helpers.py": "def util_a() -> int: return 1\n",
        "deep/__init__.py": "",
        "deep/chain.py": "from .leaf import leaf_fn\n",
        "deep/leaf.py": "def leaf_fn() -> int: return 2\n",
        "sibling.py": "thing = 3\n",
        "lazy_host.py": "host = 4\n",
        "submodule_host.py": "host = 5\n",
        "typing_only.py": "TypingThing = object\n",
        "late.py": "def arrive() -> int: return 6\n",
        "not_imported.py": "nobody = 7\n",
        "cycle_a.py": "from .cycle_b import second\nfirst = 1\n",
        "cycle_b.py": "from .cycle_a import first\nsecond = 2\n",
    }
    _make_family(tmp_path, monkeypatch, name, files)
    return name, f"{name}.main", other


# --- (a) and (b): who is in the closure, who is out -------------------------


def test_closure_includes_every_static_import_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, main, _ = _closure_family(tmp_path, monkeypatch)
    closure = import_closure(main)
    assert main in closure
    for included in (
        name,  # ancestor package __init__ of the main module
        f"{name}.helpers",  # direct
        f"{name}.deep",  # ancestor __init__ of a transitive module
        f"{name}.deep.chain",  # transitive
        f"{name}.deep.leaf",  # relative import from a transitive module
        f"{name}.sibling",  # from .sibling import thing
        f"{name}.lazy_host",  # from . import lazy_host
        f"{name}.submodule_host",  # from P import <module>
        f"{name}.typing_only",  # TYPE_CHECKING-only import
        f"{name}.late",  # function-local import
        f"{name}.cycle_a",
        f"{name}.cycle_b",
    ):
        assert included in closure, included


def test_closure_excludes_unimported_and_foreign_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, main, other = _closure_family(tmp_path, monkeypatch)
    closure = import_closure(main)
    assert f"{name}.not_imported" not in closure
    for foreign in (
        "json",
        "pydantic",
        "typing",
        "grafy_core",
        "grafy_core.artifacts",
        other,
        f"{other}.geometry",
    ):
        assert foreign not in closure
    # Nothing outside the family leaks in, under any name.
    assert all(module == name or module.startswith(f"{name}.") for module in closure)


# --- (c) what moves the digest, what must not -------------------------------


def test_digest_moves_with_any_closure_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, main, _ = _closure_family(tmp_path, monkeypatch)
    before = import_closure_digest(main)
    for changed in ("main.py", "deep/leaf.py", "deep/__init__.py", "__init__.py"):
        _write(
            tmp_path / name / changed,
            f"# touched {changed}\n"
            + (tmp_path / name / changed).read_text(encoding="utf-8"),
        )
        after = import_closure_digest(main)
        assert after != before, changed
        before = after


def test_digest_ignores_unimported_files_and_other_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, main, other = _closure_family(tmp_path, monkeypatch)
    before = import_closure_digest(main)
    assert import_closure_digest(main) == before  # stable across runs
    _write(tmp_path / name / "not_imported.py", "nobody = 700\n")
    assert import_closure_digest(main) == before
    _write(tmp_path / other / "geometry.py", "GEOMETRY = 999\n")
    assert import_closure_digest(main) == before


def test_digest_survives_a_copy_at_another_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, main, _ = _closure_family(tmp_path, monkeypatch)
    before = import_closure_digest(main)
    elsewhere = tmp_path / "checkout-2"
    shutil.copytree(tmp_path / name, elsewhere / name)
    _syspath_prepend(monkeypatch, str(elsewhere))
    importlib.invalidate_caches()
    assert import_closure_digest(main) == before


# --- (d) cycles --------------------------------------------------------------


def test_import_cycle_terminates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = _fam("cycle")
    _make_family(
        tmp_path,
        monkeypatch,
        name,
        {
            "__init__.py": "",
            "start.py": "from .ping import a\n",
            "ping.py": "from .pong import b\na = 1\n",
            "pong.py": "from .ping import a\nb = 2\n",
        },
    )
    closure = import_closure(f"{name}.start")
    assert {f"{name}.ping", f"{name}.pong"} <= closure


def test_missing_package_and_module_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = _fam("missing")
    _make_family(tmp_path, monkeypatch, name, {"__init__.py": ""})
    with pytest.raises(ModuleNotFoundError):
        import_closure(f"{name}.nope")
    with pytest.raises(ModuleNotFoundError):
        import_closure("no_such_family_at_all_xyz")


# --- (e) uv.lock parsing ------------------------------------------------------


def _lock_text(*, alpha_version: str = "1.0.0", beta_version: str = "0.9.0") -> str:
    return f'''version = 1

[[package]]
name = "proj-e"
version = "0.1.0"
source = {{ virtual = "." }}
dependencies = [
    {{ name = "alpha" }},
    {{ name = "helper" }},
    {{ name = "duplicate" }},
    {{ name = "pinned-dup", version = "2.0.0" }},
]

[package.dev-dependencies]
dev = [
    {{ name = "devonly" }},
]

[[package]]
name = "alpha"
version = "{alpha_version}"
source = {{ registry = "https://pypi.org/simple" }}
dependencies = [
    {{ name = "beta" }},
    {{ name = "workspacepkg" }},
]

[[package]]
name = "beta"
version = "{beta_version}"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "helper"
version = "3.1.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "duplicate"
version = "1.0.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "duplicate"
version = "2.0.0"
source = {{ registry = "https://pypi.org/simple" }}
marker = 'python_version < "3.13"'

[[package]]
name = "pinned-dup"
version = "1.0.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "pinned-dup"
version = "2.0.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "devonly"
version = "9.9.9"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "workspacepkg"
version = "0.1.0"
source = {{ editable = "libs/x" }}
dependencies = [
    {{ name = "wsonly" }},
]

[[package]]
name = "wsonly"
version = "8.8.8"
source = {{ registry = "https://pypi.org/simple" }}
'''


def _lock(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "uv.lock"
    _write(path, text)
    return path


def test_locked_versions_walk_transitive_third_party(tmp_path: Path) -> None:
    locked = locked_dependency_versions(_lock(tmp_path, _lock_text()), "proj-e")
    assert locked == (
        "alpha==1.0.0",
        "beta==0.9.0",
        "duplicate==1.0.0",
        "duplicate==2.0.0",
        "helper==3.1.0",
        "pinned-dup==2.0.0",
    )


def test_locked_versions_exclude_workspace_and_dev(tmp_path: Path) -> None:
    locked = locked_dependency_versions(_lock(tmp_path, _lock_text()), "proj-e")
    joined = "\n".join(locked)
    assert "devonly" not in joined  # dev-dependencies are not walked
    assert "workspacepkg" not in joined  # workspace member: not included
    assert "wsonly" not in joined  # ... and not walked through
    assert "pinned-dup==1.0.0" not in joined  # version-named entry wins


def test_locked_versions_unknown_project(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="nope-e"):
        locked_dependency_versions(_lock(tmp_path, _lock_text()), "nope-e")


def _impl_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    name = _fam("impl")
    _make_family(
        tmp_path,
        monkeypatch,
        name,
        {
            "__init__.py": "",
            "node.py": "from .depmod import d\n",
            "depmod.py": "d = 1\n",
        },
    )
    lock = tmp_path / "uv.lock"
    _write(
        lock,
        f'''version = 1

[[package]]
name = "{name.replace("_", "-")}"
version = "0.1.0"
source = {{ virtual = "." }}
dependencies = [
    {{ name = "alpha" }},
]

[[package]]
name = "alpha"
version = "1.0.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "gamma"
version = "5.0.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "other-fam"
version = "0.1.0"
source = {{ editable = "plugins/other" }}
dependencies = [
    {{ name = "gamma" }},
]
''',
    )
    return name, lock


def _digest(
    name: str,
    lock: Path,
    *,
    operator_id: str = "op.one",
    operator_version: int = 1,
    execution_epoch: str = EXECUTION_EPOCH,
) -> str:
    return implementation_digest(
        operator_id=operator_id,
        operator_version=operator_version,
        module_name=f"{name}.node",
        uv_lock=lock,
        execution_epoch=execution_epoch,
    )


def test_digest_follows_locked_versions_of_the_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, lock = _impl_family(tmp_path, monkeypatch)
    before = _digest(name, lock)
    # Rewrite the same lock with alpha at a new version.
    text = lock.read_text(encoding="utf-8").replace(
        'version = "1.0.0"', 'version = "1.0.1"'
    )
    _write(lock, text)
    assert _digest(name, lock) != before


def test_digest_ignores_versions_of_other_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, lock = _impl_family(tmp_path, monkeypatch)
    before = _digest(name, lock)
    # gamma is locked, but only the *other* family depends on it.
    text = lock.read_text(encoding="utf-8").replace(
        'name = "gamma"\nversion = "5.0.0"', 'name = "gamma"\nversion = "6.0.0"'
    )
    _write(lock, text)
    assert _digest(name, lock) == before


# --- (f) identity inputs ------------------------------------------------------


def test_epoch_operator_id_and_version_each_move_the_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, lock = _impl_family(tmp_path, monkeypatch)
    base = _digest(name, lock)
    assert base != _digest(name, lock, execution_epoch="2")
    assert base != _digest(name, lock, operator_id="op.two")
    assert base != _digest(name, lock, operator_version=2)
    assert EXECUTION_EPOCH == "1"


def test_family_project_name() -> None:
    assert family_project_name("grafy_plugin_gis.nodes") == "grafy-plugin-gis"
    assert family_project_name("grafy_core.kernel") == "grafy-core"


# --- (g) the catalog-load registry ---------------------------------------------


def test_registry_digests_known_and_unknown_operators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, lock = _impl_family(tmp_path, monkeypatch)
    digests = RegistryImplementationDigests(
        {("op.one", 1): f"{name}.node", ("op.sibling", 2): f"{name}.depmod"},
        uv_lock=lock,
    )
    known = digests.implementation_digest(make_node("n1", operator_id="op.one"))
    assert HEX_RE.match(known)
    assert known == _digest(name, lock)
    assert (
        digests.implementation_digest(
            make_node("n2", operator_id="op.sibling", operator_version=2)
        )
        != known
    )
    with pytest.raises(KeyError, match="ghost.operator"):
        digests.implementation_digest(
            make_node("n3", operator_id="ghost.operator", operator_version=1)
        )
    # A known operator id at an unknown version is also unknown.
    with pytest.raises(KeyError, match="op.one"):
        digests.implementation_digest(
            make_node("n4", operator_id="op.one", operator_version=99)
        )


# --- (h) the real repository ----------------------------------------------------


def test_real_gis_closure_stays_inside_its_family() -> None:
    closure = import_closure("grafy_plugin_gis.nodes")
    assert "grafy_plugin_gis.nodes" in closure
    assert all(
        module == "grafy_plugin_gis" or module.startswith("grafy_plugin_gis.")
        for module in closure
    )


def test_real_workbench_closure_stays_inside_its_package() -> None:
    closure = import_closure("grafy_workbench.catalog")
    assert "grafy_workbench.catalog" in closure
    assert all(
        module == "grafy_workbench" or module.startswith("grafy_workbench.")
        for module in closure
    )


def test_real_locked_versions_are_scoped_to_the_family() -> None:
    gis = locked_dependency_versions(UV_LOCK, "grafy-plugin-gis")
    assert any(entry.startswith("shapely==") for entry in gis)
    assert not any(entry.startswith("grafy-") for entry in gis)
    # Workspace members (every grafy-* package, including this one) are
    # excluded, so the walk never reaches a sibling family's dependencies.
    # Pick one third-party package the LLM or Mistral family locks but the
    # GIS family does not — its absence proves one family's dependency set
    # cannot drag another family's versions into a GIS node's identity.
    llm = set(locked_dependency_versions(UV_LOCK, "grafy-plugin-llm"))
    mistral = set(locked_dependency_versions(UV_LOCK, "grafy-plugin-mistral"))
    assert not any(entry.startswith("grafy-") for entry in llm | mistral)
    foreign = sorted((llm | mistral) - set(gis))
    assert foreign
    probe = foreign[0]
    assert probe not in gis
    # ... and it changes the *probe's* identity, so the exclusion has teeth.
    assert probe.split("==")[0] not in {entry.split("==")[0] for entry in gis}


def test_real_registry_digests_across_families() -> None:
    from grafy_api.services.families import build_application_registry

    registry = build_application_registry()
    digests = RegistryImplementationDigests.from_registry(registry, uv_lock=UV_LOCK)
    family_of: dict[tuple[str, int], str] = {}
    for registration in registry.nodes:
        node = make_node(
            "n",
            operator_id=registration.key[0],
            operator_version=registration.key[1],
        )
        digest = digests.implementation_digest(node)
        assert HEX_RE.match(digest), registration.key
        family_of[registration.key] = registration.node_class.__module__.split(".")[0]
    assert len(set(family_of.values())) >= 2
    first_family = next(iter(family_of.values()))
    other_key = next(k for k, f in family_of.items() if f != first_family)
    first_key = next(k for k, f in family_of.items() if f == first_family)
    assert digests.implementation_digest(
        make_node("a", operator_id=first_key[0], operator_version=first_key[1])
    ) != digests.implementation_digest(
        make_node("b", operator_id=other_key[0], operator_version=other_key[1])
    )

"""Write a reviewable node source bundle to stdout as a deterministic tar.gz."""

from __future__ import annotations

from gzip import GzipFile
from io import BytesIO
import os
import pathlib
import sys
import tarfile


_ROOT_FILES = frozenset({"pyproject.toml", "uv.lock", "node.json"})
_SKIP_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache", ".venv"})


def _allowed(relative: str) -> bool:
    if relative in _ROOT_FILES:
        return True
    return (
        relative.startswith("src/") or relative.startswith("tests/")
    ) and relative.endswith(".py")


def main() -> None:
    root = pathlib.Path(sys.argv[1])
    selected: list[tuple[str, bytes]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames if name not in _SKIP_DIRECTORIES
        )
        for name in sorted(filenames):
            full = pathlib.Path(dirpath, name)
            if full.is_symlink() or not full.is_file():
                continue
            relative = full.relative_to(root).as_posix()
            if not _allowed(relative):
                continue
            selected.append((relative, full.read_bytes()))
    selected.sort(key=lambda item: item[0])
    raw = BytesIO()
    with GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for relative, content in selected:
                member = tarfile.TarInfo(relative)
                member.size = len(content)
                member.mtime = 0
                member.uid = 0
                member.gid = 0
                member.mode = 0o644
                bundle.addfile(member, BytesIO(content))
    sys.stdout.buffer.write(raw.getvalue())


if __name__ == "__main__":
    main()

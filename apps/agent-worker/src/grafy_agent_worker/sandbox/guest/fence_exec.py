"""Refuse stale sandbox leases, then replace this process with the command."""

from __future__ import annotations

import os
import pathlib
import sys


def main() -> None:
    marker = pathlib.Path(sys.argv[1])
    expected = sys.argv[2]
    if marker.read_text(encoding="utf-8") != expected:
        raise RuntimeError("sandbox lease fence is stale")
    os.execvp(sys.argv[3], sys.argv[3:])


if __name__ == "__main__":
    main()

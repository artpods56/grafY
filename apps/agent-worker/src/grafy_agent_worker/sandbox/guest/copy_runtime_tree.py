"""Copy a verified node tree into the frozen runtime image."""

from __future__ import annotations

import pathlib
import shutil
import sys


def main() -> None:
    source = pathlib.Path(sys.argv[1])
    target = pathlib.Path(sys.argv[2])
    shutil.copytree(source, target, symlinks=True)


if __name__ == "__main__":
    main()

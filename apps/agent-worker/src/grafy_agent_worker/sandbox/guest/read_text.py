"""Read a sandbox file and emit its bytes to stdout if it fits the limit."""

from __future__ import annotations

import pathlib
import sys


def main() -> None:
    path = pathlib.Path(sys.argv[1])
    limit = int(sys.argv[2])
    data = path.read_bytes()
    if len(data) > limit:
        raise RuntimeError(f"file exceeds {limit} bytes")
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()

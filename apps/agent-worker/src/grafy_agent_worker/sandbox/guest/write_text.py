"""Atomically write stdin bytes to a sandbox path and print a JSON result."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile


def main() -> None:
    path = pathlib.Path(sys.argv[1])
    limit = int(sys.argv[2])
    data = sys.stdin.buffer.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"content exceeds {limit} bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    print(json.dumps({"created": created, "byte_count": len(data)}))


if __name__ == "__main__":
    main()

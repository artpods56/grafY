"""Replace exactly one occurrence of expected text and print a JSON result."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile


def main() -> None:
    path = pathlib.Path(sys.argv[1])
    limit = int(sys.argv[2])
    request = json.loads(sys.stdin.buffer.read(limit * 2 + 4096))
    data = path.read_text(encoding="utf-8")
    expected = request["expected"]
    replacement = request["replacement"]
    count = data.count(expected)
    if count != 1:
        raise RuntimeError(f"expected exactly one match but found {count}")
    raw = data.replace(expected, replacement, 1).encode()
    if len(raw) > limit:
        raise RuntimeError(f"patched file exceeds {limit} bytes")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.write(fd, raw)
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
    print(json.dumps({"replacements": 1, "byte_count": len(raw)}))


if __name__ == "__main__":
    main()

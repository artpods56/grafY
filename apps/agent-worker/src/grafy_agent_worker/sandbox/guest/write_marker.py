"""Atomically write a sandbox lease-fence marker."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile


def main() -> None:
    path = pathlib.Path(sys.argv[1])
    data = sys.argv[2].encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".fence-")
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


if __name__ == "__main__":
    main()

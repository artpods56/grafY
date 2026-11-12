"""Byte-capped on-disk cache for rendered tiles and per-image facts.

Keys are digest-addressed by the caller (source SHA-256, page, tile, renderer
version), so an entry never goes stale and nothing is ever invalidated. The
only way out is eviction: when a write pushes the total over the cap, the
least recently used entries are deleted until it fits. Writes go through a
temporary file and an atomic rename, so a reader never sees half an entry and a
crash leaves at most an orphaned temporary that the next start removes.
"""

import contextlib
import hashlib
import os
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

_TEMP_PREFIX = ".tmp-"


class DiskCache:
    def __init__(self, root: Path, max_bytes: int) -> None:
        self._root = root
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        # name -> size, least recently used first.
        self._entries: OrderedDict[str, int] = OrderedDict()
        self._total = 0
        root.mkdir(parents=True, exist_ok=True)
        self._load()

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, key: str) -> bytes | None:
        name = _name(key)
        path = self._path(name)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            with self._lock:
                self._forget(name)
            return None
        with self._lock:
            if name in self._entries:
                self._entries.move_to_end(name)
        # Persist recency so a restart evicts in the same order.
        with contextlib.suppress(OSError):
            os.utime(path)
        return data

    def put(self, key: str, data: bytes) -> None:
        if len(data) > self._max_bytes:
            return
        name = _name(key)
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{_TEMP_PREFIX}{uuid.uuid4().hex}")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        with self._lock:
            self._forget(name)
            self._entries[name] = len(data)
            self._total += len(data)
            self._evict()

    def check_writable(self) -> None:
        """Raise OSError unless a write and removal succeed. Used by health."""
        probe = self._root / f"{_TEMP_PREFIX}health-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"ok")
        finally:
            probe.unlink(missing_ok=True)

    def _path(self, name: str) -> Path:
        return self._root / name[:2] / name

    def _forget(self, name: str) -> None:
        size = self._entries.pop(name, None)
        if size is not None:
            self._total -= size

    def _evict(self) -> None:
        # Called with the lock held.
        while self._total > self._max_bytes and self._entries:
            name, size = self._entries.popitem(last=False)
            self._total -= size
            self._path(name).unlink(missing_ok=True)

    def _load(self) -> None:
        found: list[tuple[float, str, int]] = []
        for directory in self._root.iterdir():
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if not entry.is_file():
                    continue
                if entry.name.startswith(_TEMP_PREFIX):
                    entry.unlink(missing_ok=True)
                    continue
                try:
                    status = entry.stat()
                except FileNotFoundError:
                    continue
                found.append((status.st_mtime, entry.name, status.st_size))
        for _, name, size in sorted(found):
            self._entries[name] = size
            self._total += size
        with self._lock:
            self._evict()


def _name(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

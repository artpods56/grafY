import os
from pathlib import Path

import pytest

from grafy_tiler.cache import DiskCache


def _bytes(size: int, fill: int = 1) -> bytes:
    return bytes([fill]) * size


def test_round_trip_and_miss(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", 1024)
    assert cache.get("missing") is None
    cache.put("a", b"hello")
    assert cache.get("a") == b"hello"
    assert cache.total_bytes == 5
    assert cache.entry_count == 1


def test_overwrite_replaces_without_double_counting(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", 1024)
    cache.put("a", _bytes(100))
    cache.put("a", _bytes(40))
    assert cache.total_bytes == 40
    assert cache.get("a") == _bytes(40)


def test_least_recently_used_entry_is_evicted_by_byte_total(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", 300)
    cache.put("first", _bytes(100, 1))
    cache.put("second", _bytes(100, 2))
    cache.put("third", _bytes(100, 3))
    assert cache.get("first") is not None  # first is now the most recent
    cache.put("fourth", _bytes(100, 4))

    assert cache.get("second") is None  # the least recently used went
    assert cache.get("first") is not None
    assert cache.get("third") is not None
    assert cache.get("fourth") is not None
    assert cache.total_bytes == 300


def test_entry_larger_than_the_cap_is_not_stored(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", 100)
    cache.put("big", _bytes(101))
    assert cache.get("big") is None
    assert cache.total_bytes == 0


def test_restart_keeps_entries_and_evicts_oldest_first(tmp_path: Path) -> None:
    first = DiskCache(tmp_path / "cache", 1000)
    first.put("old", _bytes(100, 1))
    first.put("new", _bytes(100, 2))
    assert first.get("old") is not None  # touch: old becomes the most recent

    reopened = DiskCache(tmp_path / "cache", 150)
    assert reopened.total_bytes <= 150
    assert reopened.get("old") is not None
    assert reopened.get("new") is None


def test_orphaned_temporaries_are_removed_on_start(tmp_path: Path) -> None:
    (tmp_path / "cache" / "ab").mkdir(parents=True)
    orphan = tmp_path / "cache" / "ab" / ".tmp-deadbeef"
    orphan.write_bytes(_bytes(500))
    cache = DiskCache(tmp_path / "cache", 1024)
    assert not orphan.exists()
    assert cache.total_bytes == 0


def test_externally_deleted_file_is_forgotten(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", 1024)
    cache.put("a", b"x" * 10)
    for path in (tmp_path / "cache").rglob("*"):
        if path.is_file():
            path.unlink()
    assert cache.get("a") is None
    assert cache.total_bytes == 0


def test_a_failed_write_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = DiskCache(tmp_path / "cache", 1024)

    def broken(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        cache.put("a", b"x")
    assert list((tmp_path / "cache").rglob(".tmp-*")) == []
    assert cache.total_bytes == 0


def test_check_writable(tmp_path: Path) -> None:
    DiskCache(tmp_path / "cache", 1024).check_writable()

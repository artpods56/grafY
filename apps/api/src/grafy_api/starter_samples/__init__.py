"""Bundled public-domain sample shared by starter Projects and the empty canvas."""

from hashlib import sha256
from pathlib import Path

SAMPLE_FILENAME = "sample-historical-table.png"
SAMPLE_PATH = Path(__file__).with_name(SAMPLE_FILENAME)

_bytes: bytes | None = None
_digest: str | None = None


def sample_bytes() -> bytes:
    global _bytes, _digest
    if _bytes is None:
        _bytes = SAMPLE_PATH.read_bytes()
        _digest = sha256(_bytes).hexdigest()
    return _bytes


def sample_sha256() -> str:
    if _digest is None:
        _ = sample_bytes()
    assert _digest is not None
    return _digest


__all__ = ["SAMPLE_FILENAME", "SAMPLE_PATH", "sample_bytes", "sample_sha256"]

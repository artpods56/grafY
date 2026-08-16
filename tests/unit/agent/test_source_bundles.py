from gzip import GzipFile
from io import BytesIO
import tarfile

import pytest

from grafy_core.source_bundles import (
    MAX_SOURCE_FILE_BYTES,
    SourceBundleError,
    read_source_bundle,
)


def archive(entries: tuple[tuple[str, bytes], ...]) -> bytes:
    raw = BytesIO()
    with GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for path, content in entries:
                member = tarfile.TarInfo(path)
                member.size = len(content)
                member.mtime = 0
                bundle.addfile(member, BytesIO(content))
    return raw.getvalue()


def valid_entries() -> tuple[tuple[str, bytes], ...]:
    return (
        ("pyproject.toml", b"[project]\nname='node'\n"),
        ("uv.lock", b"version = 1\n"),
        ("node.json", b"{}\n"),
        ("src/node.py", b"def run(inputs): return inputs\n"),
        ("tests/test_node.py", b"def test_node(): assert True\n"),
    )


def test_source_bundle_reader_indexes_only_bounded_reviewable_files() -> None:
    payload = archive(valid_entries())

    index = read_source_bundle(payload)

    assert tuple(item.path for item in index.files) == (
        "node.json",
        "pyproject.toml",
        "src/node.py",
        "tests/test_node.py",
        "uv.lock",
    )
    assert index.uncompressed_byte_count == sum(
        len(content) for _, content in valid_entries()
    )


def test_source_bundle_rejects_duplicate_normalized_paths() -> None:
    payload = archive((*valid_entries(), ("./src/node.py", b"changed\n")))

    with pytest.raises(SourceBundleError, match="duplicate path"):
        read_source_bundle(payload)


def test_source_bundle_rejects_compressed_expansion_before_reading_member() -> None:
    entries = list(valid_entries())
    entries[3] = ("src/node.py", b"x" * (MAX_SOURCE_FILE_BYTES + 1))
    payload = archive(tuple(entries))

    with pytest.raises(SourceBundleError, match="exceeds"):
        read_source_bundle(payload)


def test_source_bundle_rejects_links_and_non_reviewable_paths() -> None:
    raw = BytesIO()
    with GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for path, content in valid_entries():
                member = tarfile.TarInfo(path)
                member.size = len(content)
                bundle.addfile(member, BytesIO(content))
            link = tarfile.TarInfo("src/escape.py")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            bundle.addfile(link)

    with pytest.raises(SourceBundleError, match="unsupported entry"):
        read_source_bundle(raw.getvalue())

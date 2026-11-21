import base64
import json
from pathlib import Path

import pytest
from grafy_crypto.grants import (
    Grant,
    GrantError,
    GrantSource,
    MosaicGrant,
    is_safe_key,
    mosaic_digest,
)

KEY = b"k" * 40
NOW = 1_000_000
MAX_BYTES = 1024**3


def _grant(**changes: object) -> Grant:
    fields: dict[str, object] = {
        "bucket": "bucket",
        "key": "ws/art/scan.tif",
        "sha256": "a" * 64,
        "byte_size": 100,
        "page": 0,
        "expires_at": NOW + 60,
    }
    fields.update(changes)
    return Grant(**fields)  # pyright: ignore[reportArgumentType]


def _verify(token: str, **changes: object) -> Grant:
    options: dict[str, object] = {
        "keys": [KEY],
        "bucket": "bucket",
        "now": NOW,
        "skew_seconds": 5,
        "max_source_bytes": MAX_BYTES,
    }
    options.update(changes)
    return Grant.verify_grant(token, **options)  # pyright: ignore[reportArgumentType]


def _forge(payload: dict[str, object], key: bytes = KEY) -> str:
    """A correctly signed token around an arbitrary payload."""
    from grafy_crypto.grants import _b64encode, _mac  # pyright: ignore[reportPrivateUsage]

    encoded = _b64encode(json.dumps(payload).encode())
    return f"{encoded}.{_b64encode(_mac(key, encoded))}"


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "v": 1,
        "b": "bucket",
        "k": "ws/art/scan.tif",
        "s": "a" * 64,
        "n": 100,
        "p": 0,
        "exp": NOW + 60,
    }
    payload.update(changes)
    return payload


def test_round_trip() -> None:
    grant = _grant()
    assert _verify(grant.sign_grant(KEY)) == grant


def test_either_key_verifies_so_an_operator_can_rotate() -> None:
    old, new = b"o" * 40, b"n" * 40
    token = _grant().sign_grant(old)
    assert _verify(token, keys=[new, old]) == _grant()
    with pytest.raises(GrantError):
        _verify(token, keys=[new])


def test_expiry_allows_clock_skew_but_not_more() -> None:
    token = _grant(expires_at=NOW).sign_grant(KEY)
    assert _verify(token, now=NOW + 5).expires_at == NOW
    with pytest.raises(GrantError, match="expired"):
        _verify(token, now=NOW + 6)


def test_wrong_signature_is_refused() -> None:
    token = _grant().sign_grant(b"x" * 40)
    with pytest.raises(GrantError, match="signature"):
        _verify(token)


def test_tampered_payload_is_refused() -> None:
    encoded, _, signature = _grant().sign_grant(KEY).partition(".")
    tampered = base64.urlsafe_b64encode(
        json.dumps(_payload(k="other/key.tif"), sort_keys=True).encode()
    ).rstrip(b"=")
    with pytest.raises(GrantError, match="signature"):
        _verify(f"{tampered.decode()}.{signature}")
    assert encoded


@pytest.mark.parametrize("token", ["", ".", "abc", "abc.", ".abc", "a.b.c", "!!!.!!!"])
def test_malformed_tokens_are_refused(token: str) -> None:
    with pytest.raises(GrantError):
        _verify(token)


def test_other_bucket_is_refused() -> None:
    with pytest.raises(GrantError, match="bucket"):
        _verify(_grant(bucket="elsewhere").sign_grant(KEY))


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "a/../../b.tif",
        "/absolute.tif",
        "a//b.tif",
        "a/./b.tif",
        "a/b\x00.tif",
        "",
        "x" * 1100,
        "https://evil.example/x.tif",  # a scheme is not an object key
    ],
)
def test_object_keys_that_could_leave_the_bucket_are_refused(key: str) -> None:
    with pytest.raises(GrantError):
        _verify(_forge(_payload(k=key)))


def test_safe_key_accepts_what_the_api_writes() -> None:
    assert is_safe_key("workspaces/0f3a/artifacts/ab/cdef/scan 1.tif")


@pytest.mark.parametrize(
    "changes",
    [
        {"v": 2},
        {"s": "A" * 64},
        {"s": "a" * 63},
        {"n": 0},
        {"n": MAX_BYTES + 1},
        {"n": True},
        {"n": 1.5},
        {"p": -1},
        {"p": 1024},
        {"p": "0"},
        {"exp": "soon"},
    ],
)
def test_out_of_bounds_fields_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(GrantError):
        _verify(_forge(_payload(**changes)))


def test_payload_that_is_not_an_object_is_refused() -> None:
    from grafy_crypto.grants import _b64encode, _mac  # pyright: ignore[reportPrivateUsage]

    encoded = _b64encode(b"[1, 2]")
    with pytest.raises(GrantError, match="object"):
        _verify(f"{encoded}.{_b64encode(_mac(KEY, encoded))}")


def test_golden_vectors_pin_the_wire_format() -> None:
    document = json.loads(
        Path(__file__).with_name("golden").joinpath("grant-vectors.json").read_text()
    )
    key = document["signing_key"].encode()
    for vector in document["vectors"]:
        fields = vector["grant"]
        grant = Grant(
            bucket=fields["bucket"],
            key=fields["key"],
            sha256=fields["sha256"],
            byte_size=fields["byte_size"],
            page=fields["page"],
            expires_at=fields["expires_at"],
        )
        assert grant.sign_grant(key) == vector["token"], vector["name"]
        assert (
            Grant.verify_grant(
                vector["token"],
                keys=[key],
                bucket=grant.bucket,
                now=grant.expires_at - 1,
                skew_seconds=0,
                max_source_bytes=MAX_BYTES,
            )
            == grant
        )


def _mosaic(count: int = 2) -> MosaicGrant:
    return MosaicGrant(
        bucket="bucket",
        sources=tuple(
            GrantSource(
                key=f"ws/art/{index}.tif", sha256=f"{index:x}" * 64, byte_size=100
            )
            for index in range(count)
        ),
        expires_at=NOW + 60,
    )


def _verify_mosaic(token: str, **changes: object) -> MosaicGrant:
    options: dict[str, object] = {
        "keys": [KEY],
        "bucket": "bucket",
        "now": NOW,
        "skew_seconds": 5,
        "max_source_bytes": MAX_BYTES,
    }
    options.update(changes)
    return MosaicGrant.verify_grant(token, **options)  # pyright: ignore[reportArgumentType]


def _mosaic_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "v": 1,
        "kind": "mosaic",
        "b": "bucket",
        "exp": NOW + 60,
        "src": [{"k": "ws/art/0.tif", "s": "a" * 64, "n": 100, "p": 0}],
    }
    payload.update(changes)
    return payload


def test_mosaic_round_trip_keeps_painter_order() -> None:
    grant = _mosaic(3)
    verified = _verify_mosaic(grant.sign_grant(KEY))
    assert verified == grant
    assert [single.key for single in verified.as_grants()] == [
        "ws/art/0.tif",
        "ws/art/1.tif",
        "ws/art/2.tif",
    ]
    assert all(single.expires_at == NOW + 60 for single in verified.as_grants())


def test_mosaic_and_single_grants_never_cross_verify() -> None:
    with pytest.raises(GrantError, match="kind"):
        _verify(_mosaic().sign_grant(KEY))
    with pytest.raises(GrantError):
        _verify_mosaic(_grant().sign_grant(KEY))
    with pytest.raises(GrantError, match="kind"):
        _verify(_forge(_payload(kind="single")))


def test_mosaic_expiry_bucket_and_signature_are_checked() -> None:
    token = _mosaic().sign_grant(KEY)
    with pytest.raises(GrantError, match="expired"):
        _verify_mosaic(token, now=NOW + 66)
    with pytest.raises(GrantError, match="bucket"):
        _verify_mosaic(token, bucket="other")
    with pytest.raises(GrantError, match="signature"):
        _verify_mosaic(_mosaic().sign_grant(b"x" * 40))


@pytest.mark.parametrize(
    "changes",
    [
        {"src": []},
        {"src": "nope"},
        {"src": [1]},
        {"src": [{"k": "../x", "s": "a" * 64, "n": 1, "p": 0}]},
        {"src": [{"k": "a.tif", "s": "A" * 64, "n": 1, "p": 0}]},
        {"src": [{"k": "a.tif", "s": "a" * 64, "n": 0, "p": 0}]},
        {"src": [{"k": "a.tif", "s": "a" * 64, "n": MAX_BYTES + 1, "p": 0}]},
        {"src": [{"k": "a.tif", "s": "a" * 64, "n": 1, "p": 1024}]},
        {"src": [{"k": "a.tif", "s": "a" * 64, "n": True, "p": 0}]},
        {"v": 2},
        {"exp": "soon"},
    ],
)
def test_mosaic_out_of_bounds_fields_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(GrantError):
        _verify_mosaic(_forge(_mosaic_payload(**changes)))


def test_mosaic_source_count_is_capped() -> None:
    with pytest.raises(GrantError, match="count"):
        _verify_mosaic(_mosaic(3).sign_grant(KEY), max_sources=2)


def test_mosaic_digest_depends_on_order_and_page_not_keys() -> None:
    first = GrantSource(key="a.tif", sha256="a" * 64, byte_size=1)
    second = GrantSource(key="b.tif", sha256="b" * 64, byte_size=1)
    renamed = GrantSource(key="c.tif", sha256="a" * 64, byte_size=1)
    assert mosaic_digest([first, second]) == mosaic_digest([renamed, second])
    assert mosaic_digest([first, second]) != mosaic_digest([second, first])
    paged = GrantSource(key="a.tif", sha256="a" * 64, byte_size=1, page=1)
    assert mosaic_digest([first]) != mosaic_digest([paged])

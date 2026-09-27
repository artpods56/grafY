"""Normalisation of the operator-facing absolute HTTP URLs in deployment config."""

from urllib.parse import urlsplit


def absolute_http_url(value: str) -> str:
    """Return one absolute HTTP(S) URL without its trailing slash."""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OIDC origin and issuer must be absolute HTTP URLs")
    if parsed.query or parsed.fragment:
        raise ValueError("OIDC origin and issuer must not contain query or fragment")
    return value.rstrip("/")

"""Historical Plugin contract digest fixture shared by release compatibility tests."""

from hashlib import sha256

from grafy_core.domain.plugin_releases import PluginCatalogManifest

# The empty-default fragments the digest dropped before it dropped every empty
# default. A release published in that window stored this digest form.
_PRE_CANONICALIZATION_EMPTY_FRAGMENTS = (
    ',"http_egress":null',
    ',"also_accepts":[]',
    ',"shape_field":null',
    ',"listed":true',
)


def stored_contract_digest_before_canonicalization(
    catalog: PluginCatalogManifest,
) -> str:
    """Digest a release published before empty-default canonicalization stored."""

    serialized = catalog.model_dump_json()
    for fragment in _PRE_CANONICALIZATION_EMPTY_FRAGMENTS:
        serialized = serialized.replace(fragment, "")
    return sha256(serialized.encode("utf-8")).hexdigest()

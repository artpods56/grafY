"""Historical Plugin contract digest fixtures for release compatibility tests."""

from dataclasses import replace
from hashlib import sha256

from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PluginCatalogManifest

# The empty-default fragments the digest dropped before it dropped every empty
# default. A release published in that window stored this digest form.
_PRE_CANONICALIZATION_EMPTY_FRAGMENTS = (
    ',"http_egress":null',
    ',"also_accepts":[]',
)


def stored_contract_digest_before_canonicalization(
    catalog: PluginCatalogManifest,
) -> str:
    """Digest a release published before empty-default canonicalization stored."""

    serialized = catalog.model_dump_json()
    for fragment in _PRE_CANONICALIZATION_EMPTY_FRAGMENTS:
        serialized = serialized.replace(fragment, "")
    return sha256(serialized.encode("utf-8")).hexdigest()


def persisted_row_with_digest(
    release: InstalledPluginRelease,
    contract_digest: str,
) -> InstalledPluginRelease:
    """Reshape a release the way a stored row carrying that digest looks.

    The descriptor digest is left unset so the release re-derives it: the
    fixture release chained its descriptor digest to the canonical contract
    digest, and that chain cannot verify once the stored digest is swapped in.
    """

    return InstalledPluginRelease(
        release=replace(
            release.release,
            contract_digest=contract_digest,
            descriptor_digest=None,
        ),
        installation=release.installation,
    )

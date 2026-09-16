"""Finite security capabilities declared by immutable Plugin releases."""

from enum import StrEnum


class PluginRuntimeCapability(StrEnum):
    """One exact host/runtime authority a Plugin requires to execute."""

    NODE_SECRETS = "node.secrets"
    NETWORK_EGRESS = "network.egress"
    NATIVE_GDAL = "native.gdal"
    NATIVE_TESSERACT = "native.tesseract"
    UNTRUSTED_SQL = "sql.untrusted"
    POSTGRESQL_EGRESS = "postgresql.egress"


__all__ = ["PluginRuntimeCapability"]

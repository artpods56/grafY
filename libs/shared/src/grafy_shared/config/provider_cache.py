"""How long a provider answer stays reusable, and how its rows are reclaimed.

Whether a given operation is cached at all is a decision its binding makes — see
``docs/design/provider-operation-cache.md`` — so nothing here turns caching on for
an operation that did not ask for it. These are the deployment's limits around a
cache that a binding has opted into: how long an answer may serve, how big one may
be, and how often the process sweeps the rows nobody will read again.
"""

from typing import ClassVar

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS

#: Thirty days covers a scanning campaign that revisits the same pages across a
#: project's whole working period. Anything longer keeps answers whose provider
#: revision may well have moved without the revision string having noticed.
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60


class ProviderCacheConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = {
        **SECTION_SETTINGS,
        "env_ignore_empty": True,
    }

    provider_cache_enabled: bool = True
    """Build a store at all. Off, a binding that asks for caching gets none."""

    provider_cache_ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, gt=0)
    """How long one answer may serve. An expired entry is a miss at once."""

    provider_cache_cleanup_interval_seconds: int = Field(default=900, gt=0)
    """How often one API process sweeps expired rows after writing."""

    provider_cache_cleanup_batch_rows: PositiveInt = 500
    """How many expired rows one sweep takes, so a batch stays bounded."""

    provider_cache_max_payload_bytes: PositiveInt = 2_000_000
    """An answer larger than this is not kept; the operation still returns it."""

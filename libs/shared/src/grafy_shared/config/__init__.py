"""Deployment configuration sections.

Every module here is a ``BaseSettings`` that reads one slice of the operator-facing
``GRAFY_*`` environment. This package is a **leaf**: it converts environment variables
into typed values and derives values from them alone. It never imports runtime,
service, or rendering code, which is what lets every layer import its own
configuration. See ``docs/adr/0011-shared-configuration-is-a-leaf-package.md``.
"""

from grafy_shared.config.app import AppConfig
from grafy_shared.config.auth import AuthConfig
from grafy_shared.config.egress import EgressConfig
from grafy_shared.config.execution import ExecutionConfig
from grafy_shared.config.keys import KeysConfig
from grafy_shared.config.plugins import PluginsConfig
from grafy_shared.config.realtime import RealtimeConfig
from grafy_shared.config.storage import StorageConfig
from grafy_shared.config.uploads import STAGED_UPLOAD_HARD_MAX_BYTES, UploadConfig

__all__ = [
    "STAGED_UPLOAD_HARD_MAX_BYTES",
    "AppConfig",
    "AuthConfig",
    "EgressConfig",
    "ExecutionConfig",
    "KeysConfig",
    "PluginsConfig",
    "RealtimeConfig",
    "StorageConfig",
    "UploadConfig",
]

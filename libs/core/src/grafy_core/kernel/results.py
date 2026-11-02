"""Append-only result store port (ADR 0020).

Fingerprint -> successful outputs, plus one mutable pointer per instance to its
last result and last failure. Failures are never stored by fingerprint.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import InstanceKey


@dataclass(frozen=True, slots=True)
class StoredResult:
    fingerprint: str
    outputs: Mapping[str, ArtifactOutputValue]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FailureRecord:
    fingerprint: str
    message: str
    failed_at: datetime


@dataclass(frozen=True, slots=True)
class InstancePointer:
    last_result_fingerprint: str | None
    last_failure: FailureRecord | None


class ResultStore(Protocol):
    async def get_result(self, fingerprint: str) -> StoredResult | None: ...

    async def put_result(
        self,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
    ) -> StoredResult:
        """Append once. If the fingerprint already has a result, return it unchanged."""
        ...

    async def get_pointer(self, instance: InstanceKey) -> InstancePointer | None: ...

    async def record_success(self, instance: InstanceKey, fingerprint: str) -> None:
        """Point the instance at a stored result and clear its last failure."""
        ...

    async def record_failure(
        self,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        """Keep the last result pointer; replace the last failure."""
        ...

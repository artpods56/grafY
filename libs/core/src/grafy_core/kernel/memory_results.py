"""In-memory ``ResultStore`` (ADR 0020).

Results are appended once and never mutated; the only mutable record is the
per-instance pointer to its last result and last failure.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import (
    FailureRecord,
    InstancePointer,
    StoredResult,
)


def _copied_outputs(
    outputs: Mapping[str, ArtifactOutputValue],
) -> Mapping[str, ArtifactOutputValue]:
    return MappingProxyType(
        {port: value.model_copy(deep=True) for port, value in outputs.items()}
    )


class InMemoryResultStore:
    """Dictionary-backed ``ResultStore`` for tests and single-process runs."""

    def __init__(self) -> None:
        self._results: dict[str, StoredResult] = {}
        self._pointers: dict[InstanceKey, InstancePointer] = {}

    async def get_result(self, fingerprint: str) -> StoredResult | None:
        return self._results.get(fingerprint)

    async def put_result(
        self,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
    ) -> StoredResult:
        existing = self._results.get(fingerprint)
        if existing is not None:
            return existing
        stored = StoredResult(
            fingerprint=fingerprint,
            outputs=_copied_outputs(outputs),
            created_at=datetime.now(UTC),
        )
        self._results[fingerprint] = stored
        return stored

    async def get_pointer(self, instance: InstanceKey) -> InstancePointer | None:
        return self._pointers.get(instance)

    async def record_success(self, instance: InstanceKey, fingerprint: str) -> None:
        if fingerprint not in self._results:
            raise KeyError(f"No stored result for fingerprint {fingerprint!r}")
        self._pointers[instance] = InstancePointer(
            last_result_fingerprint=fingerprint,
            last_failure=None,
        )

    async def record_failure(
        self,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        existing = self._pointers.get(instance)
        self._pointers[instance] = InstancePointer(
            last_result_fingerprint=(
                None if existing is None else existing.last_result_fingerprint
            ),
            last_failure=failure,
        )


__all__ = ["InMemoryResultStore"]

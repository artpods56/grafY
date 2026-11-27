from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.domain.feedback import FeedbackReport, FeedbackStatus
from grafy_core.ports.identity import IdentityUnitOfWorkPort


class FeedbackRepositoryPort(Protocol):
    async def add(self, report: FeedbackReport) -> None: ...

    async def get(self, report_id: UUID) -> FeedbackReport | None: ...

    async def save(self, report: FeedbackReport) -> None:
        """Write back the triage fields: status, resolution and the GitHub link."""
        ...

    async def delete(self, report_id: UUID) -> None: ...

    async def list_page(
        self,
        *,
        status: FeedbackStatus | None,
        before: datetime | None,
        limit: int,
    ) -> Sequence[FeedbackReport]:
        """Newest first; ``before`` is an exclusive bound on ``created_at``."""
        ...

    async def count_by_reporter_since(
        self, reporter_user_id: UUID, since: datetime
    ) -> int: ...


class FeedbackUnitOfWorkPort(IdentityUnitOfWorkPort, Protocol):
    @property
    def feedback(self) -> FeedbackRepositoryPort: ...


__all__ = ["FeedbackRepositoryPort", "FeedbackUnitOfWorkPort"]

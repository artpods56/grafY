"""Security-audit writes that must not take down the request they record."""

from collections.abc import Callable
from uuid import UUID

from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.ports.identity import IdentityUnitOfWorkPort

from grafy_api.diagnostics import (
    DiagnosticContext,
    diagnostic_scope,
    record_failure,
)


def failure_audit_event(
    *,
    actor_kind: SecurityAuditActorKind,
    operation: str,
    error_code: str,
    user_id: UUID | None = None,
    credential_reference: str | None = None,
    workspace_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        actor_kind=actor_kind,
        user_id=user_id,
        credential_reference=credential_reference,
        operation=operation,
        outcome=SecurityAuditOutcome.FAILURE,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        error_code=error_code,
    )


async def write_failure_audit_event(
    unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
    event: SecurityAuditEvent,
) -> None:
    try:
        async with unit_of_work_factory() as unit_of_work:
            await unit_of_work.security_audit.add(event)
            await unit_of_work.commit()
    except Exception as exc:
        context = DiagnosticContext(
            actor_id=event.user_id,
            workspace_id=event.workspace_id,
        )
        with diagnostic_scope(context, inherit=True):
            record_failure(
                exc,
                operation=f"security.audit.write.{event.operation}",
            )

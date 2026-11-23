from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from polyfactory.factories.dataclass_factory import DataclassFactory

from grafy_core.domain import (
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceRole,
    WorkspaceMembership,
)
from grafy_core.ports import IdentityUnitOfWorkPort

from tests.support.identity import seed_default_packs


class UserFactory(DataclassFactory[User]):
    __model__ = User

    email = "test@email.com"
    display_name = "Test User"
    active = True
    email_verified = True

    created_at = datetime.now(tz=timezone.utc)
    updated_at = datetime.now(tz=timezone.utc)


class WorkspaceFactory(DataclassFactory[Workspace]):
    __model__ = Workspace

    slug = "test-workspace"
    name = "Test Workspace"
    kind = WorkspaceKind.PERSONAL

    created_at = datetime.now(tz=timezone.utc)
    updated_at = datetime.now(tz=timezone.utc)


def _overrides(**values: object) -> dict[str, object]:
    return {k: v for k, v in values.items() if v is not None}


class IdentitySeeder:
    def __init__(self, unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort]):
        self.unit_of_work_factory = unit_of_work_factory

    async def user(
        self,
        *,
        email: str | None = None,
        display_name: str | None = None,
        email_verified: bool = True,
    ) -> User:
        user = UserFactory.build(
            **_overrides(email=email, display_name=display_name),
            email_verified=email_verified,
        )

        async with self.unit_of_work_factory() as uow:
            await uow.identity.add_user(user)
            await uow.commit()

        return user

    async def workspace(
        self,
        *,
        slug: str | None = None,
        name: str | None = None,
        kind: WorkspaceKind = WorkspaceKind.SHARED,
        personal_owner_user_id: UUID | None = None,
    ) -> Workspace:
        # Pass the owner explicitly even when None: shared workspaces must
        # not have one, and dropping the key lets polyfactory invent a
        # random owner that violates the shared-workspace invariant.
        workspace = WorkspaceFactory.build(
            personal_owner_user_id=(
                personal_owner_user_id if kind is WorkspaceKind.PERSONAL else None
            ),
            **_overrides(
                slug=slug,
                name=name,
                kind=kind,
            ),
        )

        async with self.unit_of_work_factory() as uow:
            await uow.identity.add_workspace(workspace)
            await seed_default_packs(uow.workspace_packs, workspace)
            await uow.commit()

        return workspace

    async def membership(
        self,
        *,
        user: User,
        workspace: Workspace,
        role: WorkspaceRole = WorkspaceRole.OWNER,
    ) -> WorkspaceMembership:
        membership = WorkspaceMembership(
            user_id=user.id,
            workspace_id=workspace.id,
            role=role,
        )

        async with self.unit_of_work_factory() as uow:
            await uow.identity.add_membership(membership)
            await uow.commit()

        return membership

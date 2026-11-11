"""HTTP surface of operator-only user disable and re-enable."""

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from grafy_api.auth import AuthService, IssuedSession
from grafy_api.settings import Settings
from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import User
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

OPERATOR_EMAIL = "ops@example.test"


def _csrf_headers(issued: IssuedSession) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": issued.csrf_value}


def _settings(settings: Settings, database_url: str) -> Settings:
    return with_setting_values(
        settings,
        database_url=SecretStr(database_url),
        operator_emails=(OPERATOR_EMAIL,),
    )


async def _issue(settings: Settings, database: Database, user: User) -> IssuedSession:
    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    auth = AuthService(
        auth=settings.auth,
        public_origin=settings.app.public_origin,
        unit_of_work_factory=unit_of_work_factory,
        identity_service=IdentityService(unit_of_work_factory),
    )
    return await auth.issue_session(user.id)


def _signed_in(client: TestClient, issued: IssuedSession) -> GrafyApi:
    api = GrafyApi(client)
    api.authenticate(issued)
    return api


async def test_an_operator_disables_and_re_enables_a_user_over_http(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "admin-users.sqlite3")
    async with db(database_url) as database:
        app_settings = _settings(settings, database_url)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        operator = await seeder.user(email=OPERATOR_EMAIL)
        target = await seeder.user(email="target@example.test")
        operator_session = await _issue(app_settings, database, operator)
        target_session = await _issue(app_settings, database, target)
        user_path = f"/v1/admin/users/{target.id}"

        with client_with_overrides(settings=app_settings) as client:
            api = _signed_in(client, operator_session)
            headers = _csrf_headers(operator_session)

            seen = client.get(user_path)
            assert seen.status_code == 200
            assert seen.json()["active"] is True

            disabled = client.post(f"{user_path}/disable", headers=headers)
            assert disabled.status_code == 200
            assert disabled.json()["id"] == str(target.id)
            assert disabled.json()["active"] is False
            assert client.get(user_path).json()["active"] is False

            # The disabled user's own session no longer authenticates.
            api.authenticate(target_session)
            assert api.auth.get_session().status_code == 401

            api.authenticate(operator_session)
            enabled = client.post(f"{user_path}/enable", headers=headers)
            assert enabled.status_code == 200
            assert enabled.json()["active"] is True

            self_disable = client.post(
                f"/v1/admin/users/{operator.id}/disable", headers=headers
            )
            assert self_disable.status_code == 409


async def test_admin_routes_refuse_non_operators_and_anonymous_callers(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "admin-users-denied.sqlite3")
    async with db(database_url) as database:
        app_settings = _settings(settings, database_url)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        member = await seeder.user(email="member@example.test")
        target = await seeder.user(email="target@example.test")
        member_session = await _issue(app_settings, database, member)
        user_path = f"/v1/admin/users/{target.id}"

        with client_with_overrides(settings=app_settings) as client:
            assert client.get(user_path).status_code == 401
            assert client.post(f"{user_path}/disable").status_code in {401, 403}

            _signed_in(client, member_session)
            headers = _csrf_headers(member_session)
            assert client.get(user_path).status_code == 403
            assert (
                client.post(f"{user_path}/disable", headers=headers).status_code == 403
            )
            assert (
                client.post(f"{user_path}/enable", headers=headers).status_code == 403
            )

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            stored = await unit_of_work.identity.get_user(target.id)
        assert stored is not None and stored.active

"""HTTP surface of feedback reports: anyone signed in sends one, operators triage."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from grafy_api.auth import AuthService, IssuedSession
from grafy_api.settings import Settings
from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import User, WorkspaceRole
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

OPERATOR_EMAIL = "ops@example.test"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
CLIENT = {
    "viewport_width": 1280,
    "viewport_height": 800,
    "device_pixel_ratio": 2,
    "user_agent": "pytest",
    "color_scheme": "dark",
}
ELEMENT = {
    "tag": "button",
    "selector": "main > button:nth-of-type(2)",
    "label": "Run",
    "role": "button",
    "test_id": None,
    "canvas_item_id": "node-1",
    "text": "Run",
    "rect": {"x": 10, "y": 20, "width": 80, "height": 32},
}


def _report(**overrides: object) -> str:
    body: dict[str, object] = {
        "kind": "bug",
        "message": "The run button does nothing",
        "page_path": "/workspaces/demo/projects/1",
        "element": ELEMENT,
        "client": CLIENT,
    }
    body.update(overrides)
    return json.dumps(body)


def _csrf_headers(issued: IssuedSession) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": issued.csrf_value}


def _settings(settings: Settings, database_url: str, tmp_path: Path) -> Settings:
    return with_setting_values(
        settings,
        database_url=SecretStr(database_url),
        operator_emails=(OPERATOR_EMAIL,),
        workspace=tmp_path / "workspace",
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


async def test_a_member_sends_feedback_and_an_operator_triages_it(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "feedback.sqlite3")
    async with db(database_url) as database:
        app_settings = _settings(settings, database_url, tmp_path)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        operator = await seeder.user(email=OPERATOR_EMAIL)
        member = await seeder.user(email="member@example.test")
        workspace = await seeder.workspace(slug="history-lab", name="History lab")
        await seeder.membership(
            user=member, workspace=workspace, role=WorkspaceRole.EDITOR
        )
        operator_session = await _issue(app_settings, database, operator)
        member_session = await _issue(app_settings, database, member)

        with client_with_overrides(settings=app_settings) as client:
            api = _signed_in(client, member_session)
            sent = client.post(
                "/v1/feedback",
                data={"report": _report(workspace_id=str(workspace.id))},
                files={"screenshot": ("shot.png", PNG, "image/png")},
                headers=_csrf_headers(member_session),
            )
            assert sent.status_code == 201, sent.text
            report_id = sent.json()["id"]
            report_path = f"/v1/admin/feedback/{report_id}"

            api.authenticate(operator_session)
            headers = _csrf_headers(operator_session)
            listed = client.get("/v1/admin/feedback")
            assert listed.status_code == 200
            [item] = listed.json()["items"]
            assert item["id"] == report_id
            assert item["status"] == "open"
            assert item["reporter"]["email"] == "member@example.test"
            assert item["workspace"]["slug"] == "history-lab"
            assert item["element"]["canvas_item_id"] == "node-1"
            assert item["screenshot"] == {
                "content_type": "image/png",
                "byte_size": len(PNG),
            }

            shot = client.get(f"{report_path}/screenshot")
            assert shot.status_code == 200
            assert shot.content == PNG
            assert shot.headers["content-type"] == "image/png"
            assert shot.headers["cache-control"] == "private, no-store"

            issue_url = "https://github.com/artpods56/grafY/issues/1"
            resolved = client.patch(
                report_path,
                json={"status": "resolved", "github_issue_url": issue_url},
                headers=headers,
            )
            assert resolved.status_code == 200
            assert resolved.json()["status"] == "resolved"
            assert resolved.json()["resolved_at"] is not None
            assert resolved.json()["github_issue_url"] == issue_url
            assert client.get("/v1/admin/feedback?status=open").json()["items"] == []
            assert (
                len(client.get("/v1/admin/feedback?status=resolved").json()["items"])
                == 1
            )

            reopened = client.patch(
                report_path, json={"status": "open"}, headers=headers
            )
            assert reopened.json()["status"] == "open"
            assert reopened.json()["resolved_at"] is None
            assert reopened.json()["github_issue_url"] == issue_url

            unlinked = client.patch(
                report_path, json={"github_issue_url": None}, headers=headers
            )
            assert unlinked.json()["github_issue_url"] is None
            not_github = client.patch(
                report_path,
                json={"github_issue_url": "https://example.com/issues/1"},
                headers=headers,
            )
            assert not_github.status_code == 422

            # A row whose object is gone answers 404 rather than failing.
            [stored] = (tmp_path / "workspace").rglob(f"{report_id}.png")
            stored.unlink()
            assert client.get(f"{report_path}/screenshot").status_code == 404

            assert client.delete(report_path, headers=headers).status_code == 204
            assert client.get(report_path).status_code == 404
            assert client.get(f"{report_path}/screenshot").status_code == 404
            assert list((tmp_path / "workspace").rglob(f"{report_id}.png")) == []


async def test_feedback_refuses_bad_screenshots_strangers_workspaces_and_floods(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "feedback-refusals.sqlite3")
    async with db(database_url) as database:
        app_settings = _settings(settings, database_url, tmp_path)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        member = await seeder.user(email="member@example.test")
        elsewhere = await seeder.workspace(slug="elsewhere", name="Elsewhere")
        member_session = await _issue(app_settings, database, member)

        with client_with_overrides(settings=app_settings) as client:
            _signed_in(client, member_session)
            headers = _csrf_headers(member_session)

            def send(**kwargs: Any) -> int:
                return client.post(
                    "/v1/feedback", headers=headers, **kwargs
                ).status_code

            assert (
                send(
                    data={"report": _report()},
                    files={"screenshot": ("shot.png", JPEG, "image/png")},
                )
                == 422
            )
            assert (
                send(
                    data={"report": _report()},
                    files={"screenshot": ("shot.gif", b"GIF89a", "image/gif")},
                )
                == 422
            )
            too_large = PNG + b"\x00" * (2 * 1024 * 1024)
            assert (
                send(
                    data={"report": _report()},
                    files={"screenshot": ("shot.png", too_large, "image/png")},
                )
                == 413
            )
            assert send(data={"report": _report(workspace_id=str(elsewhere.id))}) == 404
            assert send(data={"report": _report(message="   ")}) == 422
            assert send(data={"report": "not json"}) == 422

            for _ in range(20):
                assert send(data={"report": _report()}) == 201
            assert send(data={"report": _report()}) == 429


async def test_operator_routes_refuse_everyone_else_and_page_newest_first(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "feedback-operators.sqlite3")
    async with db(database_url) as database:
        app_settings = _settings(settings, database_url, tmp_path)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        operator = await seeder.user(email=OPERATOR_EMAIL)
        member = await seeder.user(email="member@example.test")
        operator_session = await _issue(app_settings, database, operator)
        member_session = await _issue(app_settings, database, member)

        with client_with_overrides(settings=app_settings) as client:
            assert client.get("/v1/admin/feedback").status_code == 401
            assert client.post(
                "/v1/feedback", data={"report": _report()}
            ).status_code in {401, 403}

            api = _signed_in(client, member_session)
            headers = _csrf_headers(member_session)
            sent = [
                client.post(
                    "/v1/feedback",
                    data={"report": _report(message=f"report {index}")},
                    headers=headers,
                ).json()["id"]
                for index in range(3)
            ]
            report_path = f"/v1/admin/feedback/{sent[0]}"
            assert client.get("/v1/admin/operator").json() == {"is_operator": False}
            assert client.get("/v1/admin/feedback").status_code == 403
            assert client.get(report_path).status_code == 403
            assert client.get(f"{report_path}/screenshot").status_code == 403
            assert (
                client.patch(
                    report_path, json={"status": "resolved"}, headers=headers
                ).status_code
                == 403
            )
            assert client.delete(report_path, headers=headers).status_code == 403

            api.authenticate(operator_session)
            assert client.get("/v1/admin/operator").json() == {"is_operator": True}
            first = client.get("/v1/admin/feedback", params={"limit": 2}).json()
            assert [item["id"] for item in first["items"]] == [sent[2], sent[1]]
            assert first["next_before"] is not None
            second = client.get(
                "/v1/admin/feedback",
                params={"limit": 2, "before": first["next_before"]},
            ).json()
            assert [item["id"] for item in second["items"]] == [sent[0]]
            assert second["next_before"] is None

import asyncio
from datetime import timedelta
from io import BytesIO
import tarfile
from typing import cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from grafy_core.domain.agent_authoring import (
    BuildArtifactSet,
    CapabilityManifest,
    NodeBuildStatus,
    RuntimeArtifactReference,
)
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.source_bundles import (
    GeneratedNodeBuildDocument,
    GeneratedNodeSourceDefinition,
    digest_source_subset,
    read_source_bundle,
)
from grafy_storage import LocalFileObjectStore

from grafy_api.app_state import get_app_settings, get_resources
from grafy_api.v1.routes.agent_authoring.models import (
    AgentEnvironmentListResponse,
    AgentEnvironmentResponse,
)
from grafy_api.v1.routes.saved_graphs.models import CollaborativeHeadResponse
from tests.unit.api.conftest import WORKSPACE_ID, workspace_api_path


def _create_source_graph(
    client: TestClient,
) -> tuple[UUID, CollaborativeHeadResponse]:
    created = client.post(
        workspace_api_path("/graphs"),
        json={
            "name": "Agent authoring test",
            "nodes": [
                {
                    "id": "source",
                    "operator_id": "text.input",
                    "operator_version": 1,
                    "config": {"text": "hello"},
                    "position": {"x": 20, "y": 40},
                }
            ],
            "edges": [],
        },
    )
    assert created.status_code == 201
    graph_id = UUID(created.json()["id"])
    head = client.get(workspace_api_path(f"/graphs/{graph_id}/head"))
    assert head.status_code == 200
    return graph_id, CollaborativeHeadResponse.model_validate(head.json())


def _create_environment(client: TestClient) -> AgentEnvironmentResponse:
    response = client.post(
        workspace_api_path("/agent-authoring/environments"),
        json={"name": "Python lab", "profile_slug": "python-uv"},
    )
    assert response.status_code == 201
    return AgentEnvironmentResponse.model_validate(response.json())


def _draft_payload(
    *,
    environment_id: UUID,
    head: CollaborativeHeadResponse,
    operation_id: UUID | None = None,
) -> dict[str, object]:
    resolved_operation_id = operation_id or uuid4()
    return {
        "prompt": "Append a category to every text value",
        "idempotency_key": str(resolved_operation_id),
        "environment_id": str(environment_id),
        "thread_id": None,
        "anchor": {
            "node_id": "source",
            "port_name": "text",
            "direction": "downstream",
            "artifact_type": {"id": "scalar.text", "schema_version": 1},
            "shape": "one",
        },
        "placement": {
            "node_id": "generated-on-canvas",
            "edge_id": "source-to-generated",
            "x": 340,
            "y": 40,
            "command_id": str(resolved_operation_id),
            "room_epoch": str(head.room_epoch),
            "observed_sequence": head.collaboration_sequence,
        },
    }


def test_environment_create_and_list_are_workspace_scoped(
    builtin_client: TestClient,
) -> None:
    environment = _create_environment(builtin_client)

    assert environment.name == "Python lab"
    assert environment.profile_slug == "python-uv"
    assert environment.provider == "daytona"
    assert environment.status == "provisioning"

    listed = builtin_client.get(
        workspace_api_path("/agent-authoring/environments")
    )

    assert listed.status_code == 200
    listed_environments = AgentEnvironmentListResponse.model_validate(listed.json())
    assert listed_environments.environments == [environment]


def test_create_draft_atomically_updates_graph_and_catalog_and_replays(
    builtin_client: TestClient,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    payload = _draft_payload(environment_id=environment.id, head=head)

    created = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=payload,
    )

    assert created.status_code == 202
    body = created.json()
    assert body["receipt"]["outcome"] == "accepted"
    assert body["receipt"]["deduplicated"] is False
    assert body["draft"]["operator_id"].startswith("generated.node.")
    assert body["draft"]["status"] == "authoring"
    assert body["node_spec"]["agent_authoring"] == {
        "draft_node_id": body["draft"]["id"],
        "status": "authoring",
        "runnable": False,
        "release_revision": None,
    }
    assert body["anchor_port"]["name"] == "text"
    assert [node["id"] for node in body["head"]["nodes"]] == [
        "source",
        "generated-on-canvas",
    ]
    assert body["head"]["edges"] == [
        {
            "id": "source-to-generated",
            "enabled": True,
            "from_node": "source",
            "from_port": "text",
            "to_node": "generated-on-canvas",
            "to_port": "text",
            "to_plug": None,
            "collection_mode": "direct",
            "projection": None,
            "conversion_path": [],
            "route_offset": None,
        }
    ]

    catalog = builtin_client.get(workspace_api_path("/nodes"))
    assert catalog.status_code == 200
    matching = [
        node
        for node in catalog.json()["nodes"]
        if node["operator_id"] == body["draft"]["operator_id"]
    ]
    assert matching == [body["node_spec"]]

    replay = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=payload,
    )

    assert replay.status_code == 202
    assert replay.json()["draft"]["id"] == body["draft"]["id"]
    assert replay.json()["receipt"]["outcome"] == "idempotent_replay"
    assert replay.json()["receipt"]["deduplicated"] is True
    assert replay.json()["head"]["collaboration_sequence"] == body["head"][
        "collaboration_sequence"
    ]

    detail = builtin_client.get(
        workspace_api_path(f"/agent-authoring/drafts/{body['draft']['id']}")
    )
    assert detail.status_code == 200
    assert detail.json()["draft"] == body["draft"]
    assert detail.json()["thread"] == body["thread"]
    assert detail.json()["latest_run"] == body["run"]
    assert detail.json()["latest_build"] == body["build"]
    assert detail.json()["node_spec"] == body["node_spec"]
    assert detail.json()["release"] is None
    assert detail.json()["capability_approval"] is None


def test_create_draft_requires_one_atomic_operation_id(
    builtin_client: TestClient,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    payload = _draft_payload(environment_id=environment.id, head=head)
    placement = payload["placement"]
    assert isinstance(placement, dict)
    placement["command_id"] = str(uuid4())

    response = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=payload,
    )

    assert response.status_code == 422
    assert "same atomic operation" in response.text


@pytest.mark.parametrize(
    ("anchor_update", "expected_detail"),
    [
        (
            {"artifact_type": {"id": "scalar.integer", "schema_version": 1}},
            "does not match the authoritative",
        ),
        ({"shape": "many"}, "shape does not match"),
        ({"node_id": "missing"}, "missing graph node"),
    ],
)
def test_create_draft_rejects_forged_or_stale_browser_anchor_contract(
    builtin_client: TestClient,
    anchor_update: dict[str, object],
    expected_detail: str,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    payload = _draft_payload(environment_id=environment.id, head=head)
    anchor = cast(dict[str, object], payload["anchor"])
    anchor.update(anchor_update)

    response = builtin_client.post(
        workspace_api_path(f"/agent-authoring/graphs/{graph_id}/drafts"),
        json=payload,
    )

    assert response.status_code == 422
    assert expected_detail in response.text
    unchanged = builtin_client.get(
        workspace_api_path(f"/graphs/{graph_id}/head")
    ).json()
    assert [node["id"] for node in unchanged["nodes"]] == ["source"]
    assert unchanged["edges"] == []
    catalog = builtin_client.get(workspace_api_path("/nodes")).json()
    assert not any(
        node["operator_id"].startswith("generated.node.")
        for node in catalog["nodes"]
    )


def test_graph_conflict_rolls_back_the_staged_draft_and_run(
    builtin_client: TestClient,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    operation_id = uuid4()
    payload = _draft_payload(
        environment_id=environment.id,
        head=head,
        operation_id=operation_id,
    )
    placement = payload["placement"]
    assert isinstance(placement, dict)
    placement["room_epoch"] = str(uuid4())
    before = builtin_client.get(workspace_api_path("/nodes")).json()["nodes"]

    conflicted = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=payload,
    )

    assert conflicted.status_code == 409
    after_conflict = builtin_client.get(workspace_api_path("/nodes")).json()["nodes"]
    assert after_conflict == before

    placement["room_epoch"] = str(head.room_epoch)
    accepted = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=payload,
    )

    assert accepted.status_code == 202
    assert accepted.json()["receipt"]["outcome"] == "accepted"


def test_cancelled_run_replays_durable_events_after_last_event_id(
    builtin_client: TestClient,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    created = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=_draft_payload(environment_id=environment.id, head=head),
    ).json()
    run_id = created["run"]["id"]

    cancelled = builtin_client.delete(
        workspace_api_path(f"/agent-authoring/runs/{run_id}")
    )
    detail = builtin_client.get(
        workspace_api_path(f"/agent-authoring/runs/{run_id}")
    )
    events = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/runs/{run_id}/events?after_sequence=1"
        ),
    )

    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "cancelled"
    assert detail.json()["builds"][0]["status"] == "cancelled"
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\nevent: run_status_changed\n" in events.text
    assert '"run_status":"cancelled"' in events.text
    assert "id: 1\n" not in events.text


async def _prepare_build_for_approval(
    application: FastAPI,
    *,
    environment_id: UUID,
    run_id: UUID,
    build_attempt_id: UUID,
    draft_node_id: UUID,
    bundled_capabilities: CapabilityManifest | None = None,
    build_digest_override: str | None = None,
) -> str:
    authoring = get_resources(application).agent_authoring
    environment = await authoring.get_environment(WORKSPACE_ID, environment_id)
    if environment.status == "provisioning":
        provisioning = await authoring.claim_environment_provisioning(
            workspace_id=WORKSPACE_ID,
            environment_id=environment_id,
            worker_id="api-test-provisioner",
            lease_duration=timedelta(minutes=5),
        )
        await authoring.complete_environment_provisioning(
            workspace_id=WORKSPACE_ID,
            environment_id=environment_id,
            provider_environment_id=f"local-{environment_id}",
            provisioning_token=provisioning.provisioning_token,
            provisioning_fencing_token=(
                provisioning.provisioning_fencing_token
            ),
        )
    claim = await authoring.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=run_id,
        worker_id="api-test-worker",
        lease_duration=timedelta(minutes=5),
    )
    await authoring.start_run(
        workspace_id=WORKSPACE_ID,
        run_id=run_id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
    )
    for build_status in (
        NodeBuildStatus.PREPARING,
        NodeBuildStatus.CODING,
        NodeBuildStatus.TESTING,
    ):
        await authoring.advance_build(
            workspace_id=WORKSPACE_ID,
            build_attempt_id=build_attempt_id,
            status=build_status,
            lease_token=claim.lease_token,
            fencing_token=claim.fencing_token,
        )
    draft = await authoring.get_draft(WORKSPACE_ID, draft_node_id)
    capabilities = CapabilityManifest()
    bundled_definition = GeneratedNodeSourceDefinition(
        manifest=draft.provisional_manifest,
        capabilities=bundled_capabilities or capabilities,
    )
    files = {
        "pyproject.toml": b"[project]\nname = \"generated-node\"\nversion = \"0.1.0\"\n",
        "uv.lock": b"version = 1\nrevision = 1\n",
        "node.json": (
            bundled_definition.model_dump_json(indent=2) + "\n"
        ).encode("utf-8"),
        "src/node.py": (
            b"def run(inputs: dict[str, object]) -> dict[str, object]:\n"
            b"    return {\"result\": inputs.get(\"text\")}\n"
        ),
        "tests/test_node.py": b"def test_generated_node() -> None:\n    assert True\n",
    }
    archive_stream = BytesIO()
    with tarfile.open(fileobj=archive_stream, mode="w:gz") as bundle:
        for path, content in sorted(files.items()):
            member = tarfile.TarInfo(path)
            member.size = len(content)
            member.mtime = 0
            member.mode = 0o644
            bundle.addfile(member, BytesIO(content))
    archive = archive_stream.getvalue()
    index = read_source_bundle(archive)
    source_key = (
        f"generated-nodes/{WORKSPACE_ID}/{draft_node_id}/"
        f"sources/{index.archive_sha256}.tar.gz"
    )
    settings = get_app_settings(application)
    storage = LocalFileObjectStore(settings.workspace / "objects")
    if await storage.stat(settings.storage_bucket, source_key) is None:
        await storage.save(
            SaveFileCommand(
                bucket=settings.storage_bucket,
                path=source_key,
                stream=BytesIO(archive),
                content_type="application/gzip",
                metadata={
                    "source": "agent-authoring-test",
                    "artifact_kind": "generated-node-source",
                    "sha256": index.archive_sha256,
                },
            )
        )
    runtime_artifact = RuntimeArtifactReference(
        provider="test-runtime",
        ref=f"generated-node-builds/{build_attempt_id}",
        digest="8" * 64,
    )
    build_document = GeneratedNodeBuildDocument(
        source_digest=index.archive_sha256,
        lock_digest=index.file("uv.lock").sha256,
        tests_digest=digest_source_subset(index, prefix="tests/"),
        implementation_digest=digest_source_subset(index, prefix="src/"),
        manifest=draft.provisional_manifest,
        capabilities=capabilities,
        runtime_image_digest="6" * 64,
        profile_digest="7" * 64,
        runtime_artifact=runtime_artifact,
    )
    await authoring.request_build_approval(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=build_attempt_id,
        manifest=draft.provisional_manifest,
        capabilities=capabilities,
        artifacts=BuildArtifactSet(
            source_bundle_key=source_key,
            source_digest=index.archive_sha256,
            lock_digest=index.file("uv.lock").sha256,
            tests_digest=digest_source_subset(index, prefix="tests/"),
            build_digest=build_digest_override or build_document.digest,
            implementation_digest=digest_source_subset(index, prefix="src/"),
            runtime_image_digest="6" * 64,
            profile_digest="7" * 64,
            runtime_artifact=runtime_artifact,
            tests_passed=True,
        ),
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
    )
    await authoring.complete_run_awaiting_approval(
        workspace_id=WORKSPACE_ID,
        run_id=run_id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
    )
    return capabilities.digest


def test_publish_requires_exact_approval_and_stays_non_runnable_without_worker(
    builtin_client: TestClient,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    created = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=_draft_payload(environment_id=environment.id, head=head),
    ).json()
    application = cast(FastAPI, builtin_client.app)
    capability_digest = asyncio.run(
        _prepare_build_for_approval(
            application,
            environment_id=environment.id,
            run_id=UUID(cast(str, created["run"]["id"])),
            build_attempt_id=UUID(cast(str, created["build"]["id"])),
            draft_node_id=UUID(cast(str, created["draft"]["id"])),
        )
    )

    review = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/review"
        )
    )
    assert review.status_code == 200
    review_body = review.json()
    assert review_body["build"]["capabilities"]["digest"] == capability_digest
    assert review_body["tests"]["passed"] is True
    assert review_body["tests"]["file_count"] == 1
    assert review_body["lock"]["path"] == "uv.lock"
    assert review_body["previous_release_revision"] is None
    assert {file["path"] for file in review_body["files"]} == {
        "node.json",
        "pyproject.toml",
        "src/node.py",
        "tests/test_node.py",
        "uv.lock",
    }
    assert {change["change"] for change in review_body["changes"]} == {"added"}

    source = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/"
            "review/files/src/node.py"
        )
    )
    assert source.status_code == 200
    assert source.json()["path"] == "src/node.py"
    assert "def run" in source.json()["content"]

    approval = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/approval"
        ),
        json={"capability_digest": capability_digest},
    )
    assert approval.status_code == 201
    approved_detail = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/drafts/{created['draft']['id']}"
        )
    )
    assert approved_detail.status_code == 200
    assert approved_detail.json()["capability_approval"]["id"] == (
        approval.json()["id"]
    )

    wrong_approval = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/publish"
        ),
        json={"capability_approval_id": str(uuid4())},
    )
    assert wrong_approval.status_code == 409

    published = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/publish"
        ),
        json={"capability_approval_id": approval.json()["id"]},
    )

    assert published.status_code == 201
    body = published.json()
    assert body["release"]["operator_id"] == created["draft"]["operator_id"]
    assert body["release"]["operator_version"] == 1
    assert body["release"]["capability_approval_id"] == approval.json()["id"]
    assert body["node_spec"]["agent_authoring"] == {
        "draft_node_id": created["draft"]["id"],
        "status": "published",
        "runnable": False,
        "release_revision": 1,
    }
    catalog = builtin_client.get(workspace_api_path("/nodes")).json()
    matching = [
        node
        for node in catalog["nodes"]
        if node["operator_id"] == created["draft"]["operator_id"]
    ]
    assert matching == [body["node_spec"]]


def test_follow_up_build_promotes_the_existing_graph_node_atomically(
    builtin_client: TestClient,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    created = builtin_client.post(
        workspace_api_path(f"/agent-authoring/graphs/{graph_id}/drafts"),
        json=_draft_payload(environment_id=environment.id, head=head),
    ).json()
    application = cast(FastAPI, builtin_client.app)
    capability_digest = asyncio.run(
        _prepare_build_for_approval(
            application,
            environment_id=environment.id,
            run_id=UUID(cast(str, created["run"]["id"])),
            build_attempt_id=UUID(cast(str, created["build"]["id"])),
            draft_node_id=UUID(cast(str, created["draft"]["id"])),
        )
    )
    first_approval = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/approval"
        ),
        json={"capability_digest": capability_digest},
    )
    assert first_approval.status_code == 201
    first_publication = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/publish"
        ),
        json={"capability_approval_id": first_approval.json()["id"]},
    )
    assert first_publication.status_code == 201
    assert first_publication.json()["head"] is None
    assert first_publication.json()["receipt"] is None

    follow_up_id = uuid4()
    follow_up = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/threads/{created['thread']['id']}/runs"
        ),
        json={
            "prompt": "Return the appended value in uppercase.",
            "idempotency_key": str(follow_up_id),
            "draft_node_ids": [created["draft"]["id"]],
        },
    )

    assert follow_up.status_code == 202
    follow_up_body = follow_up.json()
    assert follow_up_body["thread"]["id"] == created["thread"]["id"]
    assert follow_up_body["run"]["status"] == "queued"
    assert follow_up_body["builds"][0]["attempt_number"] == 2
    assert follow_up_body["node_specs"][0]["operator_version"] == 2
    assert follow_up_body["node_specs"][0]["agent_authoring"] == {
        "draft_node_id": created["draft"]["id"],
        "status": "authoring",
        "runnable": False,
        "release_revision": None,
    }
    replay = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/threads/{created['thread']['id']}/runs"
        ),
        json={
            "prompt": "Return the appended value in uppercase.",
            "idempotency_key": str(follow_up_id),
            "draft_node_ids": [created["draft"]["id"]],
        },
    )
    assert replay.status_code == 202
    assert replay.json()["run"]["id"] == follow_up_body["run"]["id"]
    assert replay.json()["builds"] == follow_up_body["builds"]

    second_build = follow_up_body["builds"][0]
    second_digest = asyncio.run(
        _prepare_build_for_approval(
            application,
            environment_id=environment.id,
            run_id=UUID(cast(str, follow_up_body["run"]["id"])),
            build_attempt_id=UUID(cast(str, second_build["id"])),
            draft_node_id=UUID(cast(str, created["draft"]["id"])),
        )
    )
    second_review = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/builds/{second_build['id']}/review"
        )
    )
    assert second_review.status_code == 200
    assert second_review.json()["previous_release_revision"] == 1
    second_approval = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{second_build['id']}/approval"
        ),
        json={"capability_digest": second_digest},
    )
    assert second_approval.status_code == 201

    missing_promotion = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{second_build['id']}/publish"
        ),
        json={"capability_approval_id": second_approval.json()["id"]},
    )
    assert missing_promotion.status_code == 422
    assert "graph_promotion is required" in missing_promotion.text
    after_rollback = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/drafts/{created['draft']['id']}"
        )
    ).json()
    assert after_rollback["latest_build"]["status"] == "awaiting_approval"
    assert after_rollback["release"]["revision"] == 1

    current_head = CollaborativeHeadResponse.model_validate(
        builtin_client.get(
            workspace_api_path(f"/graphs/{graph_id}/head")
        ).json()
    )
    conflicted_promotion = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{second_build['id']}/publish"
        ),
        json={
            "capability_approval_id": second_approval.json()["id"],
            "graph_promotion": {
                "graph_id": str(graph_id),
                "node_id": "generated-on-canvas",
                "command_id": str(uuid4()),
                "room_epoch": str(uuid4()),
                "observed_sequence": current_head.collaboration_sequence,
            },
        },
    )
    assert conflicted_promotion.status_code == 409
    after_graph_conflict = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/drafts/{created['draft']['id']}"
        )
    ).json()
    assert after_graph_conflict["latest_build"]["status"] == "awaiting_approval"
    assert after_graph_conflict["release"]["revision"] == 1

    promotion_id = uuid4()
    promoted = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/builds/{second_build['id']}/publish"
        ),
        json={
            "capability_approval_id": second_approval.json()["id"],
            "graph_promotion": {
                "graph_id": str(graph_id),
                "node_id": "generated-on-canvas",
                "command_id": str(promotion_id),
                "room_epoch": str(current_head.room_epoch),
                "observed_sequence": current_head.collaboration_sequence,
            },
        },
    )

    assert promoted.status_code == 201
    promoted_body = promoted.json()
    assert promoted_body["release"]["operator_version"] == 2
    assert promoted_body["node_spec"]["operator_version"] == 2
    assert promoted_body["receipt"]["command_id"] == str(promotion_id)
    assert promoted_body["receipt"]["outcome"] == "accepted"
    promoted_node = next(
        node
        for node in promoted_body["head"]["nodes"]
        if node["id"] == "generated-on-canvas"
    )
    assert promoted_node["operator_version"] == 2


def test_event_replay_rejects_invalid_last_event_id(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.get(
        workspace_api_path(f"/agent-authoring/runs/{uuid4()}/events"),
        headers={"Last-Event-ID": "not-a-sequence"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Last-Event-ID must be a non-negative integer"
    )


def test_event_replay_rejects_conflicting_header_and_query_cursors(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/runs/{uuid4()}/events?after_sequence=2"
        ),
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "after_sequence and Last-Event-ID must identify the same event"
    )


@pytest.mark.parametrize(
    ("bundled_capabilities", "build_digest_override", "error_fragment"),
    [
        (
            CapabilityManifest(
                outbound_http_origins=("https://unreviewed.example",)
            ),
            None,
            "node.json does not match",
        ),
        (None, "f" * 64, "build digest does not match"),
    ],
)
def test_build_review_rejects_semantically_tampered_bundles(
    builtin_client: TestClient,
    bundled_capabilities: CapabilityManifest | None,
    build_digest_override: str | None,
    error_fragment: str,
) -> None:
    graph_id, head = _create_source_graph(builtin_client)
    environment = _create_environment(builtin_client)
    created = builtin_client.post(
        workspace_api_path(
            f"/agent-authoring/graphs/{graph_id}/drafts"
        ),
        json=_draft_payload(environment_id=environment.id, head=head),
    ).json()
    application = cast(FastAPI, builtin_client.app)
    asyncio.run(
        _prepare_build_for_approval(
            application,
            environment_id=environment.id,
            run_id=UUID(cast(str, created["run"]["id"])),
            build_attempt_id=UUID(cast(str, created["build"]["id"])),
            draft_node_id=UUID(cast(str, created["draft"]["id"])),
            bundled_capabilities=bundled_capabilities,
            build_digest_override=build_digest_override,
        )
    )

    response = builtin_client.get(
        workspace_api_path(
            f"/agent-authoring/builds/{created['build']['id']}/review"
        )
    )

    assert response.status_code == 409
    assert error_fragment in response.json()["detail"]

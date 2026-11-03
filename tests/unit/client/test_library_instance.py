import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
from pydantic import SecretStr

from grafy_client import GrafyClient


async def test_client_saves_exact_instance_result_with_server_selected_artifact():
    workspace = UUID(int=501)
    project = UUID(int=502)
    artifact = UUID(int=503)

    async def respond(request):
        assert request.method == "POST"
        assert (
            request.url.path
            == f"/v1/workspaces/{workspace}/library/artifacts/from-instance"
        )
        assert json.loads(request.content) == {
            "project_id": str(project),
            "graph_id": "child",
            "node_id": "node",
            "call_path": ["call"],
            "map_index": None,
            "result_fingerprint": "a" * 64,
            "output_port": "value",
            "item_index": 2,
            "name": "Saved output",
        }
        return httpx.Response(
            200,
            json={
                "artifact": {
                    "artifact_id": str(artifact),
                    "artifact_type": "scalar.integer",
                    "schema_version": 1,
                    "content_type": "application/json",
                    "metadata": {},
                },
                "name": "Saved output",
                "folder_id": None,
                "provenance": {
                    "source": "instance",
                    "saved_at": datetime.now(UTC).isoformat(),
                    "project_id": str(project),
                    "project_title": "Project",
                    "graph_id": "child",
                    "graph_title": "Child",
                    "node_id": "node",
                    "node_title": "Node",
                    "call_path": ["call"],
                    "map_index": None,
                    "result_fingerprint": "a" * 64,
                    "output_port": "value",
                    "item_index": 2,
                    "name": "Saved output",
                },
            },
        )

    async with GrafyClient(
        base_url="https://testserver",
        token=SecretStr("test"),
        transport=httpx.MockTransport(respond),
    ) as client:
        item = await client.library.save_from_instance(
            workspace,
            project_id=project,
            graph_id="child",
            node_id="node",
            call_path=("call",),
            result_fingerprint="a" * 64,
            output_port="value",
            item_index=2,
            name="Saved output",
        )
    assert item.artifact.artifact_id == artifact
    assert item.provenance.call_path == ("call",)
    assert item.provenance.result_fingerprint == "a" * 64

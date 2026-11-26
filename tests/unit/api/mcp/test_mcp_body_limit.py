"""Body-size limit on the `/mcp` endpoint."""

from pathlib import Path

from grafy_api.mcp.http import MAX_MCP_REQUEST_BYTES

from tests.integration.mcp.support import ACCEPT, stage_for


def test_mcp_rejects_bodies_larger_than_four_mebibytes(tmp_path: Path) -> None:
    oversized = (
        b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"pad":"'
        + (b"a" * MAX_MCP_REQUEST_BYTES)
        + b'"}}'
    )
    with stage_for(tmp_path, "mcp-body-limit.sqlite3") as stage:
        response = stage.client.post(
            "/mcp",
            content=oversized,
            headers={
                "Accept": ACCEPT,
                "Authorization": f"Bearer {stage.editor_token}",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 413, response.text

"""Unit tests for ephemeral node live-preview reporting and SSE streaming."""

import asyncio
import json
from uuid import uuid4

import pytest
from grafy_core.node_context import (
    MAX_NODE_PREVIEW_BYTES,
    NodeExecutionContext,
)
from grafy_core.nodes import bind_active_node, emit_node_preview

from grafy_api.realtime.preview_stream import NodePreviewHub, ProjectNodePreview


def _parse_sse_chunk(chunk: str) -> tuple[str, dict[str, object]]:
    event_name = ""
    data_lines: list[str] = []
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    return event_name, json.loads("\n".join(data_lines))


@pytest.mark.asyncio
async def test_ring_buffer_caps_frames_and_resets_on_new_computation() -> None:
    hub = NodePreviewHub(max_nodes=8, max_frames_per_node=3)
    workspace_id = uuid4()
    project_id = uuid4()

    for seq in range(1, 6):
        hub.publish(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id="root",
            node_id="read_text",
            computation_id="comp-1",
            sequence=seq,
            label=f"Sheet {seq}",
            content_type="image/png",
            data=f"png-{seq}".encode(),
        )

    buffered = hub.snapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="root",
        node_id="read_text",
    )
    assert [frame.sequence for frame in buffered] == [3, 4, 5]
    assert buffered[0].data_url is not None
    assert buffered[0].data_url.startswith("data:image/png;base64,")
    assert buffered[0].text is None

    # A new computation_id replaces the previous run's frames.
    hub.publish(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="root",
        node_id="read_text",
        computation_id="comp-2",
        sequence=1,
        label="Prompt payload",
        content_type="application/json",
        data=b'{"model":"gpt-4.1-mini"}',
    )
    refreshed = hub.snapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="root",
        node_id="read_text",
    )
    assert len(refreshed) == 1
    assert refreshed[0].computation_id == "comp-2"
    assert refreshed[0].data_url is None
    assert refreshed[0].text == '{"model":"gpt-4.1-mini"}'


@pytest.mark.asyncio
async def test_lru_eviction_caps_buffered_nodes() -> None:
    hub = NodePreviewHub(max_nodes=2, max_frames_per_node=4)
    workspace_id = uuid4()
    project_id = uuid4()

    for node_id in ("n1", "n2", "n3"):
        hub.publish(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id="root",
            node_id=node_id,
            computation_id="c1",
            sequence=1,
            label=node_id,
            content_type="text/plain",
            data=node_id.encode(),
        )

    assert (
        hub.snapshot(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id="root",
            node_id="n1",
        )
        == []
    )
    assert len(
        hub.snapshot(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id="root",
            node_id="n2",
        )
    ) == 1
    assert len(
        hub.snapshot(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id="root",
            node_id="n3",
        )
    ) == 1


@pytest.mark.asyncio
async def test_sse_replays_buffered_frames_and_streams_live_updates() -> None:
    hub = NodePreviewHub(max_nodes=4, max_frames_per_node=8, keepalive_seconds=30.0)
    workspace_id = uuid4()
    project_id = uuid4()
    reporter = ProjectNodePreview(hub)
    context = NodeExecutionContext(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="root",
        node_id="node-1",
        preview_reporter=reporter,
    )

    # Emit one frame before subscribing (should be replayed immediately).
    async with bind_active_node(context):
        await emit_node_preview(
            context,
            "Sheet 1",
            data=b"\x89PNG\r\n\x1a\n",
            detail="1024x512 px",
        )

    received: list[tuple[str, dict[str, object]]] = []
    ready_event = asyncio.Event()
    second_frame_event = asyncio.Event()

    async def consume() -> None:
        async for chunk in hub.subscribe(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id="root",
            node_id="node-1",
        ):
            parsed = _parse_sse_chunk(chunk)
            received.append(parsed)
            if parsed[0] == "ready":
                ready_event.set()
            elif parsed[0] == "frame" and parsed[1]["sequence"] == 2:
                second_frame_event.set()

    consumer = asyncio.create_task(consume())
    await ready_event.wait()

    await context.preview("Sheet 2", data=b"\x89PNG\r\n\x1a\n2", detail="gpt-4.1-mini")
    await second_frame_event.wait()
    await hub.shutdown()
    await consumer

    assert received[0][0] == "ready"
    assert [item[1]["label"] for item in received[1:]] == ["Sheet 1", "Sheet 2"]
    assert received[2][1]["detail"] == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_preview_drops_oversized_payloads_and_swallows_reporter_errors() -> None:
    calls: list[str] = []

    class FailingReporter:
        async def report_preview(
            self,
            context: NodeExecutionContext,
            label: str,
            *,
            content_type: str,
            data: bytes,
            detail: str | None = None,
        ) -> None:
            del context, content_type, data, detail
            calls.append(label)
            raise RuntimeError("boom")

    context = NodeExecutionContext(
        workspace_id=uuid4(),
        project_id=uuid4(),
        graph_id="root",
        node_id="node-1",
        preview_reporter=FailingReporter(),
    )

    # Oversized payload is silently dropped without hitting the reporter.
    await context.preview("Too big", data=b"x" * (MAX_NODE_PREVIEW_BYTES + 1))
    assert calls == []

    # Reporter errors never propagate out of node execution.
    await context.preview("Valid", data="hello")
    assert calls == ["Valid"]

    # Missing context is a no-op.
    await emit_node_preview(None, "Noop", data=b"abc")

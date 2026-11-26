"""Bounded in-memory ring buffer and SSE fanout for live node preview frames."""

import asyncio
import base64
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from grafy_core.node_context import NodeExecutionContext
from pydantic import BaseModel, ConfigDict

type NodePreviewKey = tuple[UUID, UUID, str, str]


class NodePreviewFrame(BaseModel):
    """One ephemeral live-preview frame delivered over Server-Sent Events."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    computation_id: str
    label: str
    detail: str | None = None
    content_type: str
    data_url: str | None = None
    text: str | None = None
    emitted_at: str


@dataclass(slots=True)
class _NodePreviewBucket:
    computation_id: str | None = None
    frames: deque[NodePreviewFrame] = field(default_factory=deque)
    subscribers: set[asyncio.Queue[NodePreviewFrame | None]] = field(
        default_factory=set
    )


def _format_sse(event: str, data: str, *, event_id: int | None = None) -> str:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    for line in data.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


class NodePreviewHub:
    """Ephemeral per-node ring buffer with opt-in SSE subscribers.

    Memory is strictly bounded by ``max_nodes * max_frames_per_node``. Nothing
    is persisted to disk or the database: frames live only long enough for a
    user to watch a running node or inspect the most recent frames right after
    it finishes. Slow subscribers drop their own oldest queued frames and never
    backpressure node execution.
    """

    def __init__(
        self,
        *,
        max_nodes: int = 64,
        max_frames_per_node: int = 16,
        subscriber_queue_size: int = 32,
        keepalive_seconds: float = 15.0,
    ) -> None:
        self._max_nodes = max(1, max_nodes)
        self._max_frames_per_node = max(1, max_frames_per_node)
        self._subscriber_queue_size = max(1, subscriber_queue_size)
        self._keepalive_seconds = max(0.1, keepalive_seconds)
        self._buckets: OrderedDict[NodePreviewKey, _NodePreviewBucket] = OrderedDict()
        self._closed = False

    def _get_or_create_bucket(self, key: NodePreviewKey) -> _NodePreviewBucket:
        bucket = self._buckets.get(key)
        if bucket is not None:
            self._buckets.move_to_end(key)
            return bucket
        bucket = _NodePreviewBucket(frames=deque(maxlen=self._max_frames_per_node))
        self._buckets[key] = bucket
        self._evict_if_needed(keep_key=key)
        return bucket

    def _evict_if_needed(self, *, keep_key: NodePreviewKey) -> None:
        while len(self._buckets) > self._max_nodes:
            victim: NodePreviewKey | None = None
            for candidate, bucket in self._buckets.items():
                if candidate == keep_key:
                    continue
                if not bucket.subscribers:
                    victim = candidate
                    break
            if victim is None:
                for candidate in self._buckets:
                    if candidate != keep_key:
                        victim = candidate
                        break
            if victim is None:
                break
            removed = self._buckets.pop(victim)
            for queue in list(removed.subscribers):
                self._enqueue_lossy(queue, None)

    @staticmethod
    def _enqueue_lossy(
        queue: asyncio.Queue[NodePreviewFrame | None],
        item: NodePreviewFrame | None,
    ) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass

    def publish(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        computation_id: str,
        sequence: int,
        label: str,
        content_type: str,
        data: bytes,
        detail: str | None = None,
    ) -> NodePreviewFrame | None:
        if self._closed:
            return None

        if content_type.startswith("image/"):
            encoded = base64.b64encode(data).decode("ascii")
            data_url: str | None = f"data:{content_type};base64,{encoded}"
            text: str | None = None
        else:
            data_url = None
            text = data.decode("utf-8", errors="replace")

        frame = NodePreviewFrame(
            sequence=sequence,
            computation_id=computation_id,
            label=label,
            detail=detail,
            content_type=content_type,
            data_url=data_url,
            text=text,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        key: NodePreviewKey = (workspace_id, project_id, graph_id, node_id)
        bucket = self._get_or_create_bucket(key)
        if bucket.computation_id != computation_id:
            bucket.computation_id = computation_id
            bucket.frames.clear()
        bucket.frames.append(frame)

        for queue in list(bucket.subscribers):
            self._enqueue_lossy(queue, frame)
        return frame

    def snapshot(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
    ) -> list[NodePreviewFrame]:
        key: NodePreviewKey = (workspace_id, project_id, graph_id, node_id)
        bucket = self._buckets.get(key)
        if bucket is None:
            return []
        return list(bucket.frames)

    async def subscribe(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
    ) -> AsyncIterator[str]:
        if self._closed:
            return

        key: NodePreviewKey = (workspace_id, project_id, graph_id, node_id)
        bucket = self._get_or_create_bucket(key)
        queue: asyncio.Queue[NodePreviewFrame | None] = asyncio.Queue(
            maxsize=self._subscriber_queue_size
        )
        initial_frames = list(bucket.frames)
        bucket.subscribers.add(queue)
        try:
            yield _format_sse("ready", "{}")
            for frame in initial_frames:
                yield _format_sse(
                    "frame",
                    frame.model_dump_json(),
                    event_id=frame.sequence,
                )
            while not self._closed:
                try:
                    frame = await asyncio.wait_for(
                        queue.get(),
                        timeout=self._keepalive_seconds,
                    )
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if frame is None:
                    break
                yield _format_sse(
                    "frame",
                    frame.model_dump_json(),
                    event_id=frame.sequence,
                )
        finally:
            bucket.subscribers.discard(queue)
            if not bucket.subscribers and not bucket.frames:
                if self._buckets.get(key) is bucket:
                    del self._buckets[key]

    async def shutdown(self) -> None:
        self._closed = True
        for bucket in list(self._buckets.values()):
            for queue in list(bucket.subscribers):
                self._enqueue_lossy(queue, None)
            bucket.subscribers.clear()
        self._buckets.clear()


class ProjectNodePreview:
    """``NodePreviewReporter`` that publishes one node computation into a hub."""

    def __init__(self, hub: NodePreviewHub) -> None:
        self._hub = hub
        self._computation_id = str(uuid4())
        self._sequence = 0

    async def report_preview(
        self,
        context: NodeExecutionContext,
        label: str,
        *,
        content_type: str,
        data: bytes,
        detail: str | None = None,
    ) -> None:
        if (
            context.project_id is None
            or context.graph_id is None
            or context.node_id is None
        ):
            return
        self._sequence += 1
        self._hub.publish(
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            graph_id=context.graph_id,
            node_id=context.node_id,
            computation_id=self._computation_id,
            sequence=self._sequence,
            label=label,
            detail=detail,
            content_type=content_type,
            data=data,
        )


__all__ = [
    "NodePreviewFrame",
    "NodePreviewHub",
    "NodePreviewKey",
    "ProjectNodePreview",
]

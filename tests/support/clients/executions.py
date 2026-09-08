from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.v1.routes.executions.models import (
    GraphExecutionDetailResponse,
    GraphExecutionListResponse,
    GraphMaterializationsResponse,
    RunExecutionResponse,
    RunResponse,
)
from grafy_api.execution.requests import RunRequest
from grafy_core.domain.execution_history import GraphExecutionStatus

from tests.support.clients._http import _expect, _parse, _request


class ExecutionsApi:
    """The ``/v1/workspaces/{workspace_id}`` execution endpoints."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    # -- inline runs -----------------------------------------------------------

    def run(
        self,
        payload: RunRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/runs",
            payload=payload,
            headers=headers,
        )

    def run_ok(
        self,
        payload: RunRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> RunResponse:
        return _parse(RunResponse, _expect(self.run(payload, headers=headers), 200))

    # -- queued executions -------------------------------------------------------

    def start_execution(
        self,
        payload: RunRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/executions",
            payload=payload,
            headers=headers,
        )

    def start_execution_ok(
        self,
        payload: RunRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> RunExecutionResponse:
        return _parse(
            RunExecutionResponse,
            _expect(self.start_execution(payload, headers=headers), 202),
        )

    def get_execution(
        self,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/executions/{execution_id}",
            headers=headers,
        )

    def get_execution_ok(
        self,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> RunExecutionResponse:
        return _parse(
            RunExecutionResponse,
            _expect(self.get_execution(execution_id, headers=headers), 200),
        )

    def stream_execution_events(
        self,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Open the server-sent event stream of one execution.

        The route responds with ``text/event-stream``, so there is no
        ``_ok`` variant; replay requests pass ``Last-Event-ID`` via
        ``headers``.
        """

        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/executions/{execution_id}/events",
            headers=headers,
        )

    def cancel_execution(
        self,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/executions/{execution_id}",
            headers=headers,
        )

    def cancel_execution_ok(
        self,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> RunExecutionResponse:
        return _parse(
            RunExecutionResponse,
            _expect(self.cancel_execution(execution_id, headers=headers), 200),
        )

    # -- materializations and execution history ----------------------------------

    def list_materializations(
        self,
        graph_id: UUID,
        *,
        graph_revision: int,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/materializations",
            params={"graph_revision": graph_revision},
            headers=headers,
        )

    def list_materializations_ok(
        self,
        graph_id: UUID,
        *,
        graph_revision: int,
        headers: Mapping[str, str] | None = None,
    ) -> GraphMaterializationsResponse:
        return _parse(
            GraphMaterializationsResponse,
            _expect(
                self.list_materializations(
                    graph_id,
                    graph_revision=graph_revision,
                    headers=headers,
                ),
                200,
            ),
        )

    def list_graph_executions(
        self,
        graph_id: UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        graph_revision: int | None = None,
        status: GraphExecutionStatus | None = None,
        node_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        params = {
            key: value
            for key, value in (
                ("limit", limit),
                ("cursor", cursor),
                ("graph_revision", graph_revision),
                ("status", status),
                ("node_id", node_id),
            )
            if value is not None
        }
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/executions",
            params=params,
            headers=headers,
        )

    def list_graph_executions_ok(
        self,
        graph_id: UUID,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        graph_revision: int | None = None,
        status: GraphExecutionStatus | None = None,
        node_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> GraphExecutionListResponse:
        return _parse(
            GraphExecutionListResponse,
            _expect(
                self.list_graph_executions(
                    graph_id,
                    limit=limit,
                    cursor=cursor,
                    graph_revision=graph_revision,
                    status=status,
                    node_id=node_id,
                    headers=headers,
                ),
                200,
            ),
        )

    def get_graph_execution(
        self,
        graph_id: UUID,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}"
            f"/graphs/{graph_id}/executions/{execution_id}",
            headers=headers,
        )

    def get_graph_execution_ok(
        self,
        graph_id: UUID,
        execution_id: UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> GraphExecutionDetailResponse:
        return _parse(
            GraphExecutionDetailResponse,
            _expect(
                self.get_graph_execution(graph_id, execution_id, headers=headers),
                200,
            ),
        )

from collections.abc import Mapping
from uuid import UUID

from grafy_api.v1.routes.uploads.models import (
    ImageUploadItemResponse,
    SampleRequest,
    UploadTargetResponse,
)
from httpx import Response
from starlette.testclient import TestClient

from tests.support.clients._http import _expect, _parse, _parse_list, _request


class UploadsApi:
    """Workbench uploads under ``/v1/workspaces/{workspace_id}``."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    def create(
        self,
        filename: str,
        byte_size: int,
        *,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Reserve one upload and return the target its bytes should reach."""

        return self._client.post(
            f"/v1/workspaces/{self._workspace_id}/uploads",
            json={
                "filename": filename,
                "byte_size": byte_size,
                "content_type": content_type,
            },
            headers=headers,
        )

    def create_ok(
        self,
        filename: str,
        byte_size: int,
        *,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UploadTargetResponse:
        return _parse(
            UploadTargetResponse,
            _expect(
                self.create(
                    filename,
                    byte_size,
                    content_type=content_type,
                    headers=headers,
                ),
                201,
            ),
        )

    def put_content(
        self,
        target: UploadTargetResponse,
        data: bytes,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Send the bytes straight to the target the API handed back."""

        return self._client.request(
            target.method,
            target.url,
            content=data,
            headers=headers,
        )

    def complete(
        self,
        upload_id: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.post(
            f"/v1/workspaces/{self._workspace_id}/uploads/{upload_id}/complete",
            headers=headers,
        )

    def complete_ok(
        self,
        upload_id: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ImageUploadItemResponse:
        return _parse(
            ImageUploadItemResponse,
            _expect(self.complete(upload_id, headers=headers), 200),
        )

    def upload(
        self,
        filename: str,
        data: bytes,
        *,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Reserve, send, then complete one upload and return the last reply.

        A rejected reservation is returned as it stands, so callers asserting
        on authorization see the status the API chose for them.
        """

        reserved = self.create(
            filename,
            len(data),
            content_type=content_type,
            headers=headers,
        )
        if reserved.status_code >= 400:
            return reserved
        target = _parse(UploadTargetResponse, reserved)
        sent = self.put_content(target, data, headers=headers)
        if sent.status_code >= 400:
            return sent
        return self.complete(target.upload_id, headers=headers)

    def upload_ok(
        self,
        filename: str,
        data: bytes,
        *,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ImageUploadItemResponse:
        return _parse(
            ImageUploadItemResponse,
            _expect(
                self.upload(filename, data, content_type=content_type, headers=headers),
                200,
            ),
        )

    def create_samples(
        self,
        payload: SampleRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/samples",
            payload=payload,
            headers=headers,
        )

    def create_samples_ok(
        self,
        payload: SampleRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> list[ImageUploadItemResponse]:
        response = _expect(self.create_samples(payload, headers=headers), 200)
        return _parse_list(ImageUploadItemResponse, response)

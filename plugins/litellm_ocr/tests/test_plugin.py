from typing import Never

import httpx
import pytest
from grafy_api.credentials import CredentialService
from grafy_api.services.families import build_application_registry
from grafy_core.contracts.ocr import CropTextReader, TextBoxDetector
from grafy_plugin_litellm_ocr import LITELLM_OCR
from pydantic import SecretStr


def test_catalog_registers_the_litellm_providers_with_vault_credentials() -> None:
    registry = build_application_registry()
    assert LITELLM_OCR.slug == "external.litellm_ocr"
    assert {
        contract.protocol for contract in LITELLM_OCR.service_contract_dependencies
    } == {
        TextBoxDetector,
        CropTextReader,
    }
    assert {node.key for node in LITELLM_OCR.nodes} == {
        ("ocr.craft_provider", 1),
        ("ocr.paddle_cyrillic_provider", 1),
    }
    for node in LITELLM_OCR.nodes:
        assert registry.node_registration(*node.key).plugin_slug == LITELLM_OCR.slug
        assert [
            (secret.name, secret.provider_kind) for secret in node.secret_inputs
        ] == [("api_key", "litellm")]
        assert node.secret_inputs[0].verifier is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ((200,), "valid"),
        ((404, 200), "valid"),
        ((403, 200), "valid"),
        ((401, 401), "invalid"),
        ((403, 403), "unsupported"),
        ((503,), "unreachable"),
    ],
)
async def test_vault_verifies_litellm_keys_at_the_ocr_gateway(
    responses: tuple[int, ...], expected: str
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(responses[len(requests) - 1])

    def unused_database() -> Never:
        raise AssertionError("Candidate verification should not use persistence")

    vault = CredentialService(
        unit_of_work_factory=unused_database,
        plugin_registry=build_application_registry(),
        encryption_key=None,
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ),
    )

    result = await vault.verify_candidate(
        provider_kind="litellm", value=SecretStr("test-litellm-key")
    )

    assert [str(request.url) for request in requests] == [
        "https://ai-test.ihpan.edu.pl/key/info",
        "https://ai-test.ihpan.edu.pl/v1/models",
    ][: len(responses)]
    assert all(request.method == "GET" for request in requests)
    assert all(
        request.headers["Authorization"] == "Bearer test-litellm-key"
        for request in requests
    )
    assert result.status == expected
    assert "test-litellm-key" not in repr(result)
    if expected == "valid":
        assert "OCR route access is checked during a run" in result.message

import json
from functools import partial

import httpx2
import pytest
from pydantic import SecretStr
from typesafe_sdk import AsyncTypeSafeClient

from grafy_core.nodes import UserFacingNodeError
from grafy_plugin_typesafe import sdk
from grafy_plugin_typesafe.connection import TypeSafeConnectionConfig
from grafy_plugin_typesafe.models import QuestionPayload
from grafy_plugin_typesafe.sdk import SdkTypeSafeClient


def _question(question_id: str, body: object) -> QuestionPayload:
    encoded = json.dumps(body, separators=(",", ":"))
    kind = json.loads(encoded)["type"]
    return QuestionPayload(question_id=question_id, kind=kind, body=encoded)


BILLING = _question("billing", {"type": "noul", "instructions": "Billing?"})


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    captured: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200,
            headers={"x-typesafe-request-id": "req_test"},
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 12, "output_tokens": 3},
                "answers": {
                    "billing": {"type": "noul", "noul": 0.91},
                    "tone": {
                        "type": "choice",
                        "choice": "angry",
                        "confidence": 0.8,
                        "probabilities": {"calm": 0.2, "angry": 0.8},
                    },
                    "urgency": {
                        "type": "score",
                        "score": 1.2,
                        "confidence": 0.7,
                        "legend": {"0": "low", "1": "mid", "2": {"meaning": "high"}},
                        "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
                    },
                },
            },
        )

    monkeypatch.setattr(
        sdk,
        "AsyncTypeSafeClient",
        partial(
            AsyncTypeSafeClient,
            transport=httpx2.MockTransport(respond),
        ),
    )
    return captured


async def test_sdk_sends_mixed_questions_and_maps_answers(
    requests: list[httpx2.Request],
) -> None:
    questions = [
        _question(
            "billing",
            {
                "type": "noul",
                "instructions": "Is this about billing?",
                "criteria": {"true": {"example": "refund"}},
            },
        ),
        _question(
            "tone",
            {
                "type": "choice",
                "instructions": "What is the tone?",
                "criteria": {"calm": None, "angry": "Strong language"},
            },
        ),
        _question(
            "urgency",
            {
                "type": "score",
                "instructions": {"question": "How urgent?"},
                "criteria": ["low", "mid", {"meaning": "high"}],
            },
        ),
    ]
    evaluation = await SdkTypeSafeClient().evaluate(
        api_key=SecretStr("typesafe-test-key"),
        config=TypeSafeConnectionConfig(max_retries=0, timeout_seconds=5),
        state={"ticket": ["refund", None]},
        questions=questions,
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == "Bearer typesafe-test-key"
    body = json.loads(request.content)
    assert body == {
        "model": "jev-latest",
        "state": {"ticket": ["refund", None]},
        "questions": {
            "billing": {
                "type": "noul",
                "instructions": "Is this about billing?",
                "criteria": {"true": {"example": "refund"}},
            },
            "tone": {
                "type": "choice",
                "instructions": "What is the tone?",
                "criteria": {"calm": None, "angry": "Strong language"},
            },
            "urgency": {
                "type": "score",
                "instructions": {"question": "How urgent?"},
                "criteria": ["low", "mid", {"meaning": "high"}],
            },
        },
    }
    assert evaluation.model == "jev-1.13.0"
    assert evaluation.request_id == "req_test"
    assert evaluation.nouls[0].noul == 0.91
    assert evaluation.choices[0].choice == "angry"
    assert evaluation.scores[0].levels == ["low", "mid", '{"meaning":"high"}']
    assert evaluation.scores[0].probabilities["1"] == 0.6
    assert evaluation.usage.input_tokens == 12


@pytest.mark.parametrize("status", [401, 422, 429, 500])
async def test_sdk_hides_provider_bodies_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(
            status,
            headers={"x-typesafe-request-id": "req_hidden"},
            json={"detail": "ticket body sk-secret-value"},
        )

    monkeypatch.setattr(
        sdk,
        "AsyncTypeSafeClient",
        partial(
            AsyncTypeSafeClient,
            transport=httpx2.MockTransport(respond),
        ),
    )
    with pytest.raises(UserFacingNodeError, match=f"HTTP {status}") as raised:
        await SdkTypeSafeClient().evaluate(
            api_key=SecretStr("typesafe-test-key"),
            config=TypeSafeConnectionConfig(max_retries=0),
            state="hello",
            questions=[BILLING],
        )
    assert "req_hidden" in str(raised.value)
    assert "sk-secret-value" not in str(raised.value)
    assert "ticket body" not in str(raised.value)
    assert raised.value.__cause__ is not None


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {
            "billing": {
                "type": "choice",
                "choice": "yes",
                "confidence": 1.0,
                "probabilities": {"yes": 1.0},
            }
        },
    ],
)
async def test_sdk_rejects_missing_or_wrong_answer_type(
    monkeypatch: pytest.MonkeyPatch,
    answers: dict[str, object],
) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(
            200,
            json={
                "model": "jev-latest",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": answers,
            },
        )

    monkeypatch.setattr(
        sdk,
        "AsyncTypeSafeClient",
        partial(
            AsyncTypeSafeClient,
            transport=httpx2.MockTransport(respond),
        ),
    )
    with pytest.raises(UserFacingNodeError, match="could not be stored"):
        await SdkTypeSafeClient().evaluate(
            api_key=SecretStr("typesafe-test-key"),
            config=TypeSafeConnectionConfig(),
            state="hello",
            questions=[BILLING],
        )


async def test_sdk_retries_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        del request
        attempts += 1
        if attempts == 1:
            return httpx2.Response(
                429, headers={"retry-after": "0"}, json={"error": "busy"}
            )
        return httpx2.Response(
            200,
            json={
                "model": "jev-latest",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {"billing": {"type": "noul", "noul": 0.3}},
            },
        )

    monkeypatch.setattr(
        sdk,
        "AsyncTypeSafeClient",
        partial(
            AsyncTypeSafeClient,
            transport=httpx2.MockTransport(respond),
        ),
    )
    evaluation = await SdkTypeSafeClient().evaluate(
        api_key=SecretStr("key"),
        config=TypeSafeConnectionConfig(max_retries=1),
        state="hello",
        questions=[BILLING],
    )
    assert evaluation.nouls[0].noul == 0.3
    assert attempts == 2

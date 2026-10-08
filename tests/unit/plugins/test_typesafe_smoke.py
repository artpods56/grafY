import json
from functools import partial
from pathlib import Path
from typing import Literal

import httpx2
import pytest
from pydantic import SecretStr
from typesafe_sdk import AsyncTypeSafeClient

from grafy_plugin_typesafe import sdk
from scripts.smoke_typesafe import LocalGraph, run_case


@pytest.mark.parametrize("state_form", ["text", "json"])
async def test_smoke_runs_all_four_nodes_with_one_sdk_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    state_form: Literal["text", "json"],
) -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "model": "jev-test",
                "usage": {"input_tokens": 12, "output_tokens": 4},
                "answers": {
                    "billing": {"type": "noul", "noul": 0.99},
                    "route": {
                        "type": "choice",
                        "choice": "billing",
                        "confidence": 0.99,
                        "probabilities": {
                            "billing": 0.99,
                            "technical": 0.005,
                            "other": 0.005,
                        },
                    },
                    "urgency": {
                        "type": "score",
                        "score": 2.0,
                        "confidence": 0.9,
                        "legend": {"0": "none", "1": "low", "2": "today", "3": "now"},
                        "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
                    },
                    "impact": {
                        "type": "score",
                        "score": 1.0,
                        "confidence": 0.9,
                        "legend": {
                            "0": "none",
                            "1": "minor",
                            "2": "loss",
                            "3": "stopped",
                        },
                        "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0, "3": 0.0},
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
    state = (
        "Refund please"
        if state_form == "text"
        else '{"customer_message":"Refund please"}'
    )
    result = await run_case(
        LocalGraph(tmp_path, SecretStr("test-key")),
        case="billing",
        state=state,
        state_form=state_form,
        expected_route="billing",
        expected_billing="yes",
        model="jev-test",
        prepare_only=False,
    )
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert set(body["questions"]) == {"billing", "route", "urgency", "impact"}
    assert body["state"] == (
        "Refund please"
        if state_form == "text"
        else {"customer_message": "Refund please"}
    )
    assert result.status == "passed"
    assert result.billing_decision is not None
    assert result.billing_decision.outcome == "yes"
    assert result.route_decision is not None
    assert result.route_decision.outcome == "billing"
    assert result.combined_score is not None
    assert abs(result.combined_score.value - 7 / 12) < 1e-9
    assert "test-key" not in result.model_dump_json()

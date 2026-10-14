"""Command-batch validation shared by the room protocol and the HTTP request model."""

from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

import pytest
from pydantic import ValidationError

from grafy_api.graph_contracts import SubmitGraphCommandRequest
from grafy_api.realtime.protocol import GraphCommandSubmitMessage
from grafy_core.domain.collaboration import (
    AddNodeCommand,
    GraphCommand,
    RenameGraphCommand,
)
from grafy_core.domain.saved_graphs import GraphPoint, SavedGraphNode


class BatchSubmission(Protocol):
    """What batch handling reads on any command submission, room or HTTP."""

    command: GraphCommand | None

    @property
    def batch(self) -> tuple[GraphCommand, ...]: ...


def _rename(name: str) -> RenameGraphCommand:
    return RenameGraphCommand(name=name, expected_name="Draft")


def _add_node(node_id: str) -> AddNodeCommand:
    return AddNodeCommand(
        node=SavedGraphNode(
            kind="builtin",
            id=node_id,
            operator_id="example.operator",
            operator_version=1,
            position=GraphPoint(x=0, y=0),
        )
    )


def _room_message(payload: dict[str, Any]) -> BatchSubmission:
    return GraphCommandSubmitMessage.model_validate(
        {
            "protocol_version": 1,
            "type": "graph.command.submit",
            "command_id": str(uuid4()),
            "room_epoch": str(uuid4()),
            "observed_sequence": 3,
            **payload,
        }
    )


def _http_request(payload: dict[str, Any]) -> BatchSubmission:
    return SubmitGraphCommandRequest.model_validate(
        {
            "command_id": str(uuid4()),
            "room_epoch": str(uuid4()),
            "observed_sequence": 3,
            **payload,
        }
    )


_BUILDERS: tuple[Callable[[dict[str, Any]], BatchSubmission], ...] = (
    _room_message,
    _http_request,
)


@pytest.mark.parametrize("build", _BUILDERS, ids=("room", "http"))
def test_batch_submission_exposes_the_batch(
    build: Callable[[dict[str, Any]], BatchSubmission],
) -> None:
    first = _rename("Renamed")
    second = _add_node("n1")

    submitted = build({"commands": [first, second]})

    assert submitted.command is None
    assert submitted.batch == (first, second)


@pytest.mark.parametrize("build", _BUILDERS, ids=("room", "http"))
def test_single_command_submission_is_a_batch_of_one(
    build: Callable[[dict[str, Any]], BatchSubmission],
) -> None:
    command = _rename("Renamed")

    submitted = build({"command": command})

    assert submitted.command == command
    assert submitted.batch == (command,)


@pytest.mark.parametrize("build", _BUILDERS, ids=("room", "http"))
def test_submitting_both_command_and_commands_is_rejected(
    build: Callable[[dict[str, Any]], BatchSubmission],
) -> None:
    with pytest.raises(
        ValidationError, match="Set exactly one of command and commands"
    ):
        build({"command": _rename("Renamed"), "commands": [_add_node("n1")]})


@pytest.mark.parametrize("build", _BUILDERS, ids=("room", "http"))
def test_submitting_neither_command_nor_commands_is_rejected(
    build: Callable[[dict[str, Any]], BatchSubmission],
) -> None:
    with pytest.raises(
        ValidationError, match="Set exactly one of command and commands"
    ):
        build({})


@pytest.mark.parametrize("build", _BUILDERS, ids=("room", "http"))
def test_submitting_an_empty_batch_is_rejected(
    build: Callable[[dict[str, Any]], BatchSubmission],
) -> None:
    with pytest.raises(ValidationError):
        build({"commands": []})

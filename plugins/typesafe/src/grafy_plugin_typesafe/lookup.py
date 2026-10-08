from grafy_plugin_typesafe.models import (
    ChoiceAnswerPayload,
    EvaluationPayload,
    NoulAnswerPayload,
    ScoreAnswerPayload,
)
from grafy_plugin_typesafe.parsing import require_question_id


def find_noul(evaluation: EvaluationPayload, question_id: str) -> NoulAnswerPayload:
    _ = require_question_id(question_id)
    for answer in evaluation.nouls:
        if answer.question_id == question_id:
            return answer
    raise ValueError(_missing("noul", question_id, evaluation))


def find_choice(evaluation: EvaluationPayload, question_id: str) -> ChoiceAnswerPayload:
    _ = require_question_id(question_id)
    for answer in evaluation.choices:
        if answer.question_id == question_id:
            return answer
    raise ValueError(_missing("choice", question_id, evaluation))


def find_score(evaluation: EvaluationPayload, question_id: str) -> ScoreAnswerPayload:
    _ = require_question_id(question_id)
    for answer in evaluation.scores:
        if answer.question_id == question_id:
            return answer
    raise ValueError(_missing("score", question_id, evaluation))


def _missing(kind: str, question_id: str, evaluation: EvaluationPayload) -> str:
    found = answer_kind(question_id, evaluation)
    if found is None:
        return f"Evaluation has no answer named {question_id!r}"
    return f"Answer {question_id!r} is a {found}, not a {kind}"


def answer_kind(question_id: str, evaluation: EvaluationPayload) -> str | None:
    if any(answer.question_id == question_id for answer in evaluation.nouls):
        return "noul"
    if any(answer.question_id == question_id for answer in evaluation.choices):
        return "choice"
    if any(answer.question_id == question_id for answer in evaluation.scores):
        return "score"
    return None

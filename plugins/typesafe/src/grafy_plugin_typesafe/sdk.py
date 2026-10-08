import json
from collections.abc import Sequence

from pydantic import SecretStr, ValidationError

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    NoulCriteria,
    RetryPolicy,
    Score,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPITimeoutError,
    TypeSafeError,
)

from grafy_core.nodes import UserFacingNodeError

from grafy_plugin_typesafe.connection import TypeSafeConnectionConfig, shown
from grafy_plugin_typesafe.models import (
    ChoiceAnswerPayload,
    EvaluationPayload,
    NoulAnswerPayload,
    QuestionPayload,
    ScoreAnswerPayload,
    UsagePayload,
)
from grafy_plugin_typesafe.parsing import (
    JsonContent,
    JsonValue,
    parse_question_body,
)


class SdkTypeSafeClient:
    """TypeSafe SDK adapter. One client is opened per call and then closed."""

    async def evaluate(
        self,
        *,
        api_key: SecretStr,
        config: TypeSafeConnectionConfig,
        state: JsonContent,
        questions: Sequence[QuestionPayload],
    ) -> EvaluationPayload:
        sdk_questions = {
            question.question_id: _sdk_question(question) for question in questions
        }
        try:
            async with AsyncTypeSafeClient(
                api_key=api_key.get_secret_value(),
                base_url=config.base_url,
                model=config.model,
                timeout=config.timeout_seconds,
                retry=_retry_policy(config),
            ) as client:
                # SDK 0.7 uses string-based recursive aliases that Pyright cannot resolve.
                response = await client.system_one(  # pyright: ignore[reportUnknownMemberType]
                    state=state,
                    questions=sdk_questions,
                    model=config.model,
                    response_model=SystemOneResponse,
                )
        except Exception as exc:
            raise _provider_failure(
                exc,
                config=config,
                question_count=len(questions),
            ) from exc
        try:
            return _evaluation(response, config=config, questions=questions)
        except (ValidationError, ValueError) as exc:
            raise UserFacingNodeError(
                "TypeSafe returned an evaluation that could not be stored for "
                f"model {config.model!r} and base URL {config.base_url!r}"
            ) from exc


def _retry_policy(config: TypeSafeConnectionConfig) -> RetryPolicy:
    budget = config.timeout_seconds * (config.max_retries + 1) + config.max_retries
    return RetryPolicy(max_retries=config.max_retries, timeout=budget)


def _sdk_question(question: QuestionPayload) -> Noul | Choice | Score:
    kind, instructions, criteria = parse_question_body(
        question.body,
        expected_kind=question.kind,
    )
    content = instructions
    if kind == "noul":
        return Noul(instructions=content, criteria=_noul_criteria(criteria))
    if kind == "choice":
        if not isinstance(criteria, dict):
            raise ValueError("Choice criteria must be an object")
        return Choice(instructions=content, criteria=_choice_criteria(criteria))
    if not isinstance(criteria, list):
        raise ValueError("Score levels must be an array")
    levels: list[JsonContent] = []
    for level in criteria:
        if not isinstance(level, str | dict | list):
            raise ValueError("Score level must be a string, object, or array")
        levels.append(level)
    return Score(instructions=content, criteria=levels)


def _noul_criteria(criteria: JsonValue | None) -> NoulCriteria | None:
    if criteria is None:
        return None
    if not isinstance(criteria, dict):
        raise ValueError("Noul criteria must be an object")
    built: NoulCriteria = {}
    if "true" in criteria:
        built["true"] = _content_or_none(criteria["true"])
    if "false" in criteria:
        built["false"] = _content_or_none(criteria["false"])
    return built or None


def _choice_criteria(criteria: dict[str, JsonValue]) -> dict[str, JsonContent | None]:
    built: dict[str, JsonContent | None] = {}
    for label, description in criteria.items():
        built[label] = _content_or_none(description)
    return built


def _content_or_none(value: JsonValue) -> JsonContent | None:
    if value is None:
        return None
    if isinstance(value, str | dict | list):
        return value
    raise ValueError("Question content must be a string, object, array, or null")


def _evaluation(
    response: SystemOneResponse,
    *,
    config: TypeSafeConnectionConfig,
    questions: Sequence[QuestionPayload],
) -> EvaluationPayload:
    nouls: list[NoulAnswerPayload] = []
    choices: list[ChoiceAnswerPayload] = []
    scores: list[ScoreAnswerPayload] = []
    for question in questions:
        answer = response.answers.get(question.question_id)
        if isinstance(answer, NoulAnswer) and question.kind == "noul":
            nouls.append(
                NoulAnswerPayload(question_id=question.question_id, noul=answer.noul)
            )
            continue
        if isinstance(answer, ChoiceAnswer) and question.kind == "choice":
            choices.append(
                ChoiceAnswerPayload(
                    question_id=question.question_id,
                    choice=answer.choice,
                    confidence=answer.confidence,
                    probabilities=dict(answer.probabilities),
                )
            )
            continue
        if isinstance(answer, ScoreAnswer) and question.kind == "score":
            scores.append(_score_answer(question.question_id, answer))
            continue
        raise ValueError(
            f"TypeSafe omitted or returned the wrong answer type for {question.question_id!r}"
        )
    return EvaluationPayload(
        requested_model=config.model,
        model=response.model,
        base_url=config.base_url,
        request_id=_request_id(response),
        usage=UsagePayload(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        ),
        nouls=nouls,
        choices=choices,
        scores=scores,
    )


def _score_answer(question_id: str, answer: ScoreAnswer) -> ScoreAnswerPayload:
    levels = [_render_level(answer.legend[index]) for index in sorted(answer.legend)]
    probabilities = {
        str(index): probability for index, probability in answer.probabilities.items()
    }
    return ScoreAnswerPayload(
        question_id=question_id,
        score=answer.score,
        confidence=answer.confidence,
        levels=levels,
        probabilities=probabilities,
    )


def _render_level(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list):
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    raise ValueError("Score level must be a string, object, or array")


def _request_id(response: SystemOneResponse) -> str | None:
    try:
        return response.request_id
    except TypeSafeError:
        return None


def _provider_failure(
    exc: Exception,
    *,
    config: TypeSafeConnectionConfig,
    question_count: int,
) -> UserFacingNodeError:
    if isinstance(exc, UserFacingNodeError):
        return exc
    if isinstance(exc, ValueError) and not isinstance(exc, ValidationError):
        return shown(exc)
    if isinstance(exc, TypeSafeAPITimeoutError):
        detail = "TypeSafe request timed out"
    elif isinstance(exc, TypeSafeAPIConnectionError):
        detail = "TypeSafe request could not reach the API"
    elif isinstance(exc, TypeSafeAPIError):
        request = f", request {exc.request_id}" if exc.request_id else ""
        detail = f"TypeSafe returned HTTP {exc.status}{request}"
    elif isinstance(exc, TypeSafeError):
        detail = "TypeSafe rejected the client configuration"
    elif isinstance(exc, ValidationError):
        detail = "TypeSafe returned data the node could not read"
    else:
        detail = "TypeSafe request failed"
    counted = f"{question_count} question{'' if question_count == 1 else 's'}"
    return UserFacingNodeError(
        f"{detail} for model {config.model!r}, base URL {config.base_url!r}, "
        f"and {counted}"
    )

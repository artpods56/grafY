from collections.abc import Sequence
from typing import Protocol

from pydantic import SecretStr

from grafy_plugin_typesafe.connection import TypeSafeConnectionConfig
from grafy_plugin_typesafe.models import EvaluationPayload, QuestionPayload
from grafy_plugin_typesafe.parsing import JsonContent


class TypeSafePort(Protocol):
    async def evaluate(
        self,
        *,
        api_key: SecretStr,
        config: TypeSafeConnectionConfig,
        state: JsonContent,
        questions: Sequence[QuestionPayload],
    ) -> EvaluationPayload: ...

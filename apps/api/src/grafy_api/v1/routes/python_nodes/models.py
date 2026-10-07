from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field

from grafy_api.python_nodes import (
    MAX_PYTHON_CODE_LENGTH,
    PythonApplyResult,
    PythonCodeContract,
    PythonDiagnostic,
)
from grafy_api.v1.models import ApiResponse, PluginReleasePinModel


class ApplyPythonCodeRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    code: str = Field(max_length=MAX_PYTHON_CODE_LENGTH)
    plugin_release: PluginReleasePinModel = Field(
        description="The Python runner release the node pins."
    )


class ApplyPythonCodeResponse(ApiResponse):
    code_sha256: str
    contract: PythonCodeContract | None = Field(
        description="The ports and params schema to store; null when diagnostics block Apply."
    )
    diagnostics: list[PythonDiagnostic]

    @classmethod
    def from_result(cls, result: PythonApplyResult) -> Self:
        return cls(
            code_sha256=result.code_sha256,
            contract=result.contract,
            diagnostics=list(result.diagnostics),
        )


__all__ = ["ApplyPythonCodeRequest", "ApplyPythonCodeResponse"]

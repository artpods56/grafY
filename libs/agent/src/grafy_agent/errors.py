import re


class AgentRuntimeError(RuntimeError):
    """A coding-agent operation could not be completed safely."""


class AgentConfigurationError(AgentRuntimeError):
    """Required model or sandbox configuration is missing or invalid."""


class SandboxOperationError(AgentRuntimeError):
    """A sandbox operation failed with its operation context preserved."""


class SandboxPathError(SandboxOperationError):
    """A requested path escapes its assigned node project."""


class StaleAgentLeaseError(AgentRuntimeError):
    """The worker no longer owns the run it attempted to mutate."""


def bounded_error_detail(value: str, *, max_characters: int = 3_000) -> str:
    normalized = value.strip()
    if len(normalized) <= max_characters:
        return normalized
    suffix = f"… [truncated from {len(normalized)} characters]"
    if len(suffix) >= max_characters:
        return suffix[:max_characters]
    return f"{normalized[: max_characters - len(suffix)]}{suffix}"


def terminal_error(operation: str, error: BaseException) -> str:
    """Render a bounded terminal diagnostic without common credential shapes."""

    try:
        detail = str(error)
    except Exception:
        detail = "exception detail unavailable"
    detail = "".join(
        character if character.isprintable() else " " for character in detail
    )
    detail = re.sub(r"\s+", " ", detail).strip()
    if detail == "":
        detail = "no exception detail"

    credential_name = (
        r"(?:authorization|proxy[-_ ]?authorization|cookie|set[-_ ]?cookie|"
        r"x[-_ ]?api[-_ ]?key|x[-_ ]?auth[-_ ]?token|api[-_ ]?key|"
        r"access[-_ ]?token|refresh[-_ ]?token|id[-_ ]?token|client[-_ ]?secret|"
        r"private[-_ ]?key|password|passwd|token|secret|credential)"
    )
    quoted_credential = re.compile(
        rf"(?i)(?P<prefix>['\"]?{credential_name}['\"]?\s*[:=]\s*)"
        r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
    )
    detail = quoted_credential.sub(
        r"\g<prefix>\g<quote>[redacted]\g<quote>",
        detail,
    )
    detail = re.sub(
        rf"(?i)({credential_name}\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,;}}\]]+",
        r"\1[redacted]",
        detail,
    )
    detail = re.sub(
        rf"(?i)([?&]{credential_name}=)[^&\s]+",
        r"\1[redacted]",
        detail,
    )
    detail = re.sub(
        r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 [redacted]",
        detail,
    )
    detail = re.sub(
        r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@",
        r"\1[redacted]@",
        detail,
    )
    rendered = f"{operation} failed ({type(error).__name__}): {detail}"
    return bounded_error_detail(rendered, max_characters=3_900)


__all__ = [
    "AgentConfigurationError",
    "AgentRuntimeError",
    "SandboxOperationError",
    "SandboxPathError",
    "StaleAgentLeaseError",
    "bounded_error_detail",
    "terminal_error",
]

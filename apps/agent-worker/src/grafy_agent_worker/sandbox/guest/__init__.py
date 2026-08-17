"""Host loader for stdlib-only programs executed inside the sandbox.

The worker injects these sources through `python3 -c` so the agent-writable
workspace cannot replace them. Each sibling module is a self-contained guest
program; it must not import Grafy packages.
"""

import re
from functools import lru_cache
from importlib.resources import files

_PROGRAM_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@lru_cache(maxsize=None)
def program(name: str) -> str:
    if _PROGRAM_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid sandbox guest program name {name!r}")
    source = (
        files("grafy_agent_worker.sandbox.guest")
        .joinpath(f"{name}.py")
        .read_text(encoding="utf-8")
    )
    if source.strip() == "":
        raise FileNotFoundError(f"sandbox guest program {name!r} is empty")
    return source


__all__ = ["program"]

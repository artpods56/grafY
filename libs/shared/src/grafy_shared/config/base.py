"""The environment-reading contract shared by every configuration section."""

from pathlib import Path
from typing import TypeVar

from pydantic_settings import BaseSettings, SettingsConfigDict

# Every section reads the same flat ``GRAFY_*`` namespace and the same optional
# ``.env`` file, so an operator-facing variable never moves when a field moves
# between sections. ``extra="ignore"`` is mandatory here: each section sees the
# other sections' variables in the environment and must not reject them.
SECTION_SETTINGS: SettingsConfigDict = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_prefix="GRAFY_",
    extra="ignore",
)

SectionT = TypeVar("SectionT", bound=BaseSettings)


def read_section(section: type[SectionT], *, env_file: str | Path | None) -> SectionT:
    """Read one section, choosing whether a ``.env`` file is read at all.

    ``env_file=None`` means "ignore ``.env`` completely", which is how the composed
    ``Settings.from_environment`` keeps one environment-read decision for all nine
    sections instead of leaving each caller to repeat it. The argument is a real
    pydantic-settings runtime parameter; only its generated ``__init__`` stub is
    missing it, so the suppression lives here once rather than at every call site.
    """

    return section(_env_file=env_file)  # pyright: ignore[reportCallIssue]

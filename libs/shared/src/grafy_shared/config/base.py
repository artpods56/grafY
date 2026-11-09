from pydantic_settings import SettingsConfigDict

SECTION_SETTINGS: SettingsConfigDict = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_prefix="GRAFY_",
    extra="ignore",
)

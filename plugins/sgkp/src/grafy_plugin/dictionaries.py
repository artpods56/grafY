from functools import cache
from io import StringIO

from grafy_plugin.processing import load_abbreviations, load_settlement_type_mapping
from grafy_plugin.resources.abbreviations import ABBREVIATION_GLOSSARY
from grafy_plugin.resources.settlement_types import SETTLEMENT_TYPE_CSV


@cache
def bundled_settlement_mapping() -> dict[str, str]:
    return load_settlement_type_mapping(StringIO(SETTLEMENT_TYPE_CSV))


@cache
def bundled_abbreviations() -> tuple[str, dict[str, str]]:
    return load_abbreviations(StringIO(ABBREVIATION_GLOSSARY))

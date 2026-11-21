from uuid import uuid4

from grafy_core.artifact_contracts import MarkdownValue
from grafy_core.node_context import NodeExecutionContext
from grafy_workbench.table.markdown_tables import (
    ExtractMarkdownTablesConfig,
    ExtractMarkdownTablesInput,
    ExtractMarkdownTablesNode,
)


async def test_extracts_html_tables_with_spans_banners_headers_and_required_columns() -> (
    None
):
    markdown = """
### 1. Могилевскій уѣздъ.

<table>
  <tr>
    <th rowspan="2">№</th>
    <th rowspan="2">Волость</th>
    <th rowspan="2">Сѣдзиба</th>
    <th colspan="2">Населеніе</th>
  </tr>
  <tr>
    <th>Мужчинъ</th>
    <th>Женщинъ</th>
  </tr>
  <tr><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td></tr>
  <tr><td>1</td><td>1. Бѣлыничская . . . .</td><td>м. Бѣлыничи . . . .</td><td>1900</td><td>1932</td></tr>
  <tr><td colspan="5">2. Быховскій уѣздъ.</td></tr>
  <tr><td></td><td></td><td>Въ уѣздѣ . . . .</td><td>1900</td><td>1932</td></tr>
  <tr><td>13</td><td>1. Баханьская. . . .</td><td>с. Бахань . . . .</td><td>1200</td><td>1250</td></tr>
</table>
"""
    result = await ExtractMarkdownTablesNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        ExtractMarkdownTablesConfig(
            column_names=["no", "volost", "seat", "male", "female"],
            skip_table_headers=True,
            include_section_column=True,
            required_columns=["volost", "seat"],
            strip_leader_dots=True,
        ),
        ExtractMarkdownTablesInput(markdown=MarkdownValue(markdown=markdown)),
    )

    assert [col.id for col in result.table.columns] == [
        "section",
        "no",
        "volost",
        "seat",
        "male",
        "female",
    ]
    assert result.table.rows == [
        {
            "section": "1. Могилевскій уѣздъ.",
            "no": "1",
            "volost": "1. Бѣлыничская",
            "seat": "м. Бѣлыничи",
            "male": "1900",
            "female": "1932",
        },
        {
            "section": "2. Быховскій уѣздъ.",
            "no": "13",
            "volost": "1. Баханьская",
            "seat": "с. Бахань",
            "male": "1200",
            "female": "1250",
        },
    ]


async def test_extracts_gfm_pipe_table_with_inferred_headers() -> None:
    markdown = """
## Sample section

| Name | Score |
| --- | --- |
| Горки | 0.95 |
| Орша | 0.88 |
"""
    result = await ExtractMarkdownTablesNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        ExtractMarkdownTablesConfig(include_section_column=True),
        ExtractMarkdownTablesInput(markdown=MarkdownValue(markdown=markdown)),
    )

    assert [(col.id, col.title) for col in result.table.columns] == [
        ("section", "Section"),
        ("column_1", "Name"),
        ("column_2", "Score"),
    ]
    assert result.table.rows == [
        {"section": "Sample section", "column_1": "Горки", "column_2": "0.95"},
        {"section": "Sample section", "column_1": "Орша", "column_2": "0.88"},
    ]

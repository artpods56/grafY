/** Curated colors for known artifact types, used for port dots and edge strokes. */
const ARTIFACT_TYPE_COLOR: Record<string, string> = {
  "image.raster": "light-dark(#2a9d7c, #43c59e)",
  "ocr.page_result": "light-dark(#7b63c9, #9a7cf2)",
  "ocr.document_result": "light-dark(#7b63c9, #9a7cf2)",
  "ocr.request_trace": "light-dark(#c9920f, #fbbf24)",
  "ocr.response_trace": "light-dark(#c9920f, #fbbf24)",
  "extraction.record_result": "light-dark(#c35a91, #f472b6)",
  "extraction.document_result": "light-dark(#c35a91, #f472b6)",
  "evaluation.metrics": "light-dark(#c9920f, #fbbf24)",
  "scalar.integer": "light-dark(#4590c7, #57a5ef)",
  "scalar.text": "light-dark(#b46735, #e88a50)",
  "text.markdown": "light-dark(#b46735, #e88a50)",
  "json.schema": "light-dark(#8b5fbf, #b07ce8)",
  "prompt.message": "light-dark(#a96f1f, #e2a448)",
  "llm.completion": "light-dark(#6f63bd, #9285e8)",
  "table.page": "light-dark(#3c9aa1, #4bc0c8)",
  "table.data": "light-dark(#237f8d, #3db0bd)",
  "tabular.csv_bundle": "light-dark(#c08549, #f0a65a)",
  "export.dataset": "light-dark(#8663c9, #a78bfa)",
  "geo.feature_collection": "light-dark(#27865f, #3fbf88)",
  "geo.raster_scan": "light-dark(#758c2c, #a4c83e)",
  "geo.map_layer": "light-dark(#1f8892, #35b7c3)",
  "geo.map_document": "light-dark(#2370a8, #45a1df)",
  "sql.statement": "light-dark(#a0642d, #d98b45)",
  "sql.result": "light-dark(#357f9f, #50acd0)",
};

const ARTIFACT_TYPE_FAMILY_COLOR: Record<string, string> = {
  image: "light-dark(#2a9d7c, #43c59e)",
  ocr: "light-dark(#7b63c9, #9a7cf2)",
  extraction: "light-dark(#c35a91, #f472b6)",
  evaluation: "light-dark(#c9920f, #fbbf24)",
  scalar: "light-dark(#4590c7, #57a5ef)",
  text: "light-dark(#b46735, #e88a50)",
  json: "light-dark(#8b5fbf, #b07ce8)",
  prompt: "light-dark(#a96f1f, #e2a448)",
  llm: "light-dark(#6f63bd, #9285e8)",
  table: "light-dark(#237f8d, #3db0bd)",
  tabular: "light-dark(#c08549, #f0a65a)",
  export: "light-dark(#8663c9, #a78bfa)",
  geo: "light-dark(#27865f, #3fbf88)",
  sql: "light-dark(#357f9f, #50acd0)",
};

export function artifactTypeColor(
  artifactTypeId: string,
  fallback: string,
): string {
  const family = artifactTypeId.split(".", 1)[0];
  return (
    ARTIFACT_TYPE_COLOR[artifactTypeId] ??
    (family ? ARTIFACT_TYPE_FAMILY_COLOR[family] : undefined) ??
    fallback
  );
}

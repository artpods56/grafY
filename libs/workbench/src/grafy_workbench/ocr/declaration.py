from grafy_core.artifact_contracts import IMAGE_REGIONS, MARKDOWN, RASTER_IMAGE
from grafy_core.contracts.ocr import DocumentOcr
from grafy_core.file_contracts import PDF_FILE
from grafy_core.plugins import Plugin
from grafy_core.table_contracts import TABLE_DATA

OCR = Plugin(slug="ocr", title="OCR")
OCR.register_service_contract(DocumentOcr)
OCR.register_artifact_type_dependency(MARKDOWN)
OCR.register_artifact_type_dependency(TABLE_DATA)
OCR.register_artifact_type_dependency(IMAGE_REGIONS)
OCR.register_artifact_type_dependency(RASTER_IMAGE)
OCR.register_artifact_type_dependency(PDF_FILE)

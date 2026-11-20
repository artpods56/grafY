from grafy_workbench.ocr import (
    craft,
    georeference,
    jev_filter,
    label_studio,
    nodes,
    paddle_recognizer,
    text_regions,
    tiff_recognition,
)
from grafy_workbench.ocr.declaration import OCR

# Importing a node module registers its nodes on OCR.
_ = (
    craft,
    georeference,
    jev_filter,
    label_studio,
    nodes,
    paddle_recognizer,
    text_regions,
    tiff_recognition,
)


__all__ = ["OCR"]

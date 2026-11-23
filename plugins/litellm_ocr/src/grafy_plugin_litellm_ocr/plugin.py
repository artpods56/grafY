from grafy_plugin_litellm_ocr import (
    craft,
    paddle_recognizer,
)
from grafy_plugin_litellm_ocr.declaration import LITELLM_OCR

# Importing the node modules registers their operators.
_ = (
    craft,
    paddle_recognizer,
)

__all__ = ["LITELLM_OCR"]

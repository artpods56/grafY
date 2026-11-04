"""HTTP interface for the Grafy workbench."""

import os

# API processes never display an interactive model-library banner.
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

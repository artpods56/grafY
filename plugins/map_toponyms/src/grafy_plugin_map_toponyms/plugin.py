from grafy_plugin_map_toponyms import (
    georeference,
    jev_filter,
    label_nodes,
    label_studio,
    place_matching,
    text_regions,
    tiff_recognition,
    transliteration,
)
from grafy_plugin_map_toponyms.declaration import MAP_TOPONYMS

# Importing the node modules registers their operators.
_ = (
    georeference,
    jev_filter,
    label_nodes,
    label_studio,
    place_matching,
    text_regions,
    tiff_recognition,
    transliteration,
)

__all__ = ["MAP_TOPONYMS"]

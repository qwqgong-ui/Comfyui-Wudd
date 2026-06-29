"""ComfyUI-Wudd-V3 package entrypoint."""

from .nodes import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    WUDD_V3_NODE_CLASSES,
    comfy_entrypoint,
)

WEB_DIRECTORY = "./web"

__all__ = [
    "WEB_DIRECTORY",
    "WUDD_V3_NODE_CLASSES",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "comfy_entrypoint",
]

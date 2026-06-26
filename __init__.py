"""
ComfyUI-Wudd-V3 - V3 node package entrypoint.

This package intentionally uses unique WuddV3* node ids so it can be installed
beside the original ComfyUI-Wudd V1 package without overriding existing
workflows.
"""

from .v3_adapter import WUDD_V3_NODE_CLASSES, comfy_entrypoint

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = WUDD_V3_NODE_CLASSES
NODE_DISPLAY_NAME_MAPPINGS = {
    node_id: node_cls.GET_SCHEMA().display_name or node_id
    for node_id, node_cls in WUDD_V3_NODE_CLASSES.items()
}

__all__ = [
    "WEB_DIRECTORY",
    "WUDD_V3_NODE_CLASSES",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "comfy_entrypoint",
]

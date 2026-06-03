"""
ComfyUI-Wudd-V3 - V3 node package entrypoint.

This package intentionally uses unique WuddV3* node ids so it can be installed
beside the original ComfyUI-Wudd V1 package without overriding existing
workflows.
"""

from .v3_adapter import WUDD_V3_NODE_CLASSES, comfy_entrypoint

WEB_DIRECTORY = "./web"

__all__ = ["WEB_DIRECTORY", "WUDD_V3_NODE_CLASSES", "comfy_entrypoint"]

"""Compatibility facade for the split ChatGPT browser backend."""

from .browser_1_scripts import BROWSER_CONNECTION_MODES, DEFAULT_CDP_URL, SUBMIT_ACTIONS
from .browser_2_runtime import _is_cdp_ready
from .browser_6_node import WuddChatGPTBrowser

__all__ = [
    "BROWSER_CONNECTION_MODES",
    "DEFAULT_CDP_URL",
    "SUBMIT_ACTIONS",
    "WuddChatGPTBrowser",
    "_is_cdp_ready",
]

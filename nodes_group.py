"""
Group control helper nodes.
"""

from .nodes_common import WUDD_CATEGORY


class WuddGroupSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Master toggle for all listed canvas groups. If group_name is set, it controls only that group.",
                    },
                ),
                "group_name": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "Leave empty to show and control all canvas groups. Use self/current/auto for the containing group, or type an exact group title.",
                    },
                ),
                "off_mode": (
                    ["mute", "bypass"],
                    {
                        "default": "mute",
                        "tooltip": "mute sets group nodes to Never; bypass sets group nodes to Bypass.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("BOOLEAN", "STRING")
    RETURN_NAMES = ("enabled", "group_name")
    FUNCTION = "switch_group"
    CATEGORY = WUDD_CATEGORY

    def switch_group(self, enabled, group_name="", off_mode="mute"):
        return (bool(enabled), group_name or "")

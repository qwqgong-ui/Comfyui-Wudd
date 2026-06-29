"""Core implementation for WuddPathJoiner."""
import re

from .common import WUDD_CATEGORY

class WuddPathJoiner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "count":     ("INT",    {"default": 2, "min": 1, "max": 5}),
                "segment_1": ("STRING", {"default": ""}),
                "segment_2": ("STRING", {"default": ""}),
                "segment_3": ("STRING", {"default": ""}),
                "segment_4": ("STRING", {"default": ""}),
                "segment_5": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("path",)
    FUNCTION = "join_path"
    CATEGORY = WUDD_CATEGORY

    def join_path(self, count, segment_1, segment_2, segment_3, segment_4, segment_5):
        all_segments = [segment_1, segment_2, segment_3, segment_4, segment_5]
        parts = [s for s in all_segments[:count] if s.strip()]
        return ("/".join(parts),)

__all__ = [
    "WuddPathJoiner",
]

"""
ComfyUI-Wudd — 文本类节点。

包含：
    WuddTextSplitter        按行切分多行文本，取第 index 行
    WuddMultiTextSplitter   多行文本一次分到 16 个输出（动态按 count 显示）
    WuddPathJoiner          用 `/` 串联最多 5 段路径片段
"""

from .nodes_common import WUDD_CATEGORY


class WuddTextSplitter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "index": ("INT", {"default": 0, "min": 0, "max": 99999}),
                "skip_empty": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "split_text"
    CATEGORY = WUDD_CATEGORY

    def split_text(self, text, index, skip_empty=False):
        lines = text.splitlines()
        if skip_empty:
            lines = [line for line in lines if line.strip()]
        if 0 <= index < len(lines):
            return (lines[index],)
        return ("",)


class WuddMultiTextSplitter:
    MAX_OUTPUTS = 16  # JS 端同步保持此上限

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "count": ("INT", {"default": 2, "min": 1, "max": cls.MAX_OUTPUTS}),
                "skip_empty": ("BOOLEAN", {"default": False}),
            }
        }

    # 固定声明最大数量；JS 动态隐藏多余的输出槽
    RETURN_TYPES = ("STRING",) * MAX_OUTPUTS
    RETURN_NAMES = tuple(f"line_{i}" for i in range(MAX_OUTPUTS))
    FUNCTION = "split_text"
    CATEGORY = WUDD_CATEGORY

    def split_text(self, text, count, skip_empty=False):
        lines = text.splitlines()
        if skip_empty:
            lines = [line for line in lines if line.strip()]
        # 返回恰好 MAX_OUTPUTS 个值；超出 count 的槽只是空字符串，前端不连接即可
        max_count = max(1, min(int(count), self.MAX_OUTPUTS))
        return tuple(
            lines[i] if i < max_count and i < len(lines) else ""
            for i in range(self.MAX_OUTPUTS)
        )


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

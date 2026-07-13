"""Core implementation for WuddMultiTextSplitter."""
class WuddMultiTextSplitter:
    MAX_OUTPUTS = 16  # JS 端同步保持此上限

    # 固定声明最大数量；JS 动态隐藏多余的输出槽

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

__all__ = [
    "WuddMultiTextSplitter",
]

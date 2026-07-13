"""Core implementation for WuddTextSplitter."""
class WuddTextSplitter:
    def split_text(self, text, index, skip_empty=False):
        lines = text.splitlines()
        if skip_empty:
            lines = [line for line in lines if line.strip()]
        if 0 <= index < len(lines):
            return (lines[index],)
        return ("",)

__all__ = [
    "WuddTextSplitter",
]

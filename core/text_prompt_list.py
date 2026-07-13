"""Core implementation for WuddPromptListFromText."""
import re

class WuddPromptListFromText:
    _NUMBERING_RE = re.compile(
        r"^\s*(?:[-*]\s+|(?:第\s*)?\d+\s*(?:页|[.、)\-]|[:：](?!\d))\s*|page\s*\d+\s*[:：.)-]?\s*)",
        re.IGNORECASE,
    )

    @classmethod
    def _clean_line(cls, line, strip_numbering):
        line = line.strip()
        if strip_numbering:
            line = cls._NUMBERING_RE.sub("", line).strip()
        return line

    def to_list(self, text, skip_empty=True, strip_numbering=True):
        prompts = []
        for raw_line in text.splitlines():
            line = self._clean_line(raw_line, strip_numbering)
            if line in {"```", "```text", "```markdown"}:
                continue
            if skip_empty and not line:
                continue
            if len(line) <= 12 and any(key in line for key in ("页数", "总页数", "提示词")):
                continue
            prompts.append(line)
        return (prompts, len(prompts))

__all__ = [
    "WuddPromptListFromText",
]

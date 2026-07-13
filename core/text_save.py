"""Core implementation for WuddSaveText."""

from __future__ import annotations

import os

import folder_paths


class WuddSaveText:
    ROOT_DIRS = ("output", "input", "temp")
    SAVE_MODES = ("overwrite", "append", "new_only")

    @classmethod
    def _root_directory(cls, root_dir):
        root_dir = str(root_dir or "output")
        if root_dir == "output":
            return folder_paths.get_output_directory()
        if root_dir == "input":
            return folder_paths.get_input_directory()
        if root_dir == "temp":
            return folder_paths.get_temp_directory()
        raise ValueError(f"Unsupported root_dir: {root_dir!r}")

    @staticmethod
    def _relative_file(file):
        value = str(file or "").strip().strip("\"'")
        if not value:
            value = "Wudd_Text.txt"
        value = value.replace("\\", "/")
        if os.path.isabs(value):
            raise ValueError("Text file path must be relative to root_dir.")

        normalized = os.path.normpath(value)
        if normalized in ("", "."):
            normalized = "Wudd_Text.txt"
        if normalized == ".." or normalized.startswith(f"..{os.sep}"):
            raise ValueError("Text file path cannot escape root_dir.")
        return normalized

    @classmethod
    def _resolve_path(cls, root_dir, file):
        base_dir = os.path.abspath(cls._root_directory(root_dir))
        rel_file = cls._relative_file(file)
        file_path = os.path.abspath(os.path.join(base_dir, rel_file))
        if os.path.commonpath((base_dir, file_path)) != base_dir:
            raise ValueError("Text file path cannot escape root_dir.")
        return file_path

    @staticmethod
    def _normalize_mode(append):
        mode = str(append or "overwrite")
        if mode in {"false", "False"}:
            return "overwrite"
        if mode in {"true", "True"}:
            return "append"
        if mode in {"new only", "new-only", "new"}:
            return "new_only"
        if mode not in WuddSaveText.SAVE_MODES:
            raise ValueError(f"Unsupported save mode: {append!r}")
        return mode

    def save_text(self, text, root_dir="output", file="Wudd_Text.txt", append="overwrite", insert=False):
        file_path = self._resolve_path(root_dir, file)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        content = "" if text is None else str(text)
        mode = self._normalize_mode(append)

        if mode == "overwrite":
            with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        elif mode == "new_only":
            with open(file_path, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        elif insert:
            existing = ""
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as handle:
                    existing = handle.read()
            with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.write(existing)
        else:
            with open(file_path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(content)

        return (file_path,)


__all__ = [
    "WuddSaveText",
]

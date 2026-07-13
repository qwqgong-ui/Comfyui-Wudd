from __future__ import annotations

from .._base import *


class WuddV3PromptListFromText(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddPromptListFromText

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3PromptListFromText",
            display_name="Wudd V3 Prompt List From Text",
            category=TEXT_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Boolean.Input("skip_empty", default=True),
                IO.Boolean.Input("strip_numbering", default=True),
            ],
            outputs=[
                IO.String.Output("prompts", display_name="prompts", is_output_list=True),
                IO.Int.Output("count", display_name="count"),
            ],
        ))

    @classmethod
    async def execute(cls, text, skip_empty=True, strip_numbering=True) -> IO.NodeOutput:
        return await cls._run_backend(
            "to_list",
            text=text,
            skip_empty=skip_empty,
            strip_numbering=strip_numbering,
        )


__all__ = ["WuddV3PromptListFromText"]

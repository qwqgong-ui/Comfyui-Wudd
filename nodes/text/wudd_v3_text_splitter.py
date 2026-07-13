from __future__ import annotations

from .._base import *


class WuddV3TextSplitter(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddTextSplitter

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3TextSplitter",
            display_name="Wudd V3 Text Splitter",
            category=TEXT_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Int.Input("index", default=0, min=0, max=99999),
                IO.Boolean.Input("skip_empty", default=False),
            ],
            outputs=[IO.String.Output("text", display_name="text")],
        ))

    @classmethod
    async def execute(cls, text, index, skip_empty=False) -> IO.NodeOutput:
        return await cls._run_backend("split_text", text=text, index=index, skip_empty=skip_empty)


__all__ = ["WuddV3TextSplitter"]

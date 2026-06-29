from __future__ import annotations

from ._base import *


class WuddV3MultiTextSplitter(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddMultiTextSplitter

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3MultiTextSplitter",
            display_name="Wudd V3 Multi Text Splitter",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Int.Input("count", default=2, min=1, max=WuddMultiTextSplitter.MAX_OUTPUTS),
                IO.Boolean.Input("skip_empty", default=False),
            ],
            outputs=[
                IO.String.Output(f"line_{i}", display_name=f"line_{i}")
                for i in range(WuddMultiTextSplitter.MAX_OUTPUTS)
            ],
        )

    @classmethod
    async def execute(cls, text, count, skip_empty=False) -> IO.NodeOutput:
        return await cls._run_backend("split_text", text=text, count=count, skip_empty=skip_empty)


__all__ = ["WuddV3MultiTextSplitter"]

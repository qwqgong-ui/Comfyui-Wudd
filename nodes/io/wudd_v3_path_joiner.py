from __future__ import annotations

from .._base import *


class WuddV3PathJoiner(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddPathJoiner

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3PathJoiner",
            display_name="Wudd V3 Path Joiner",
            category=IO_CATEGORY,
            inputs=[
                IO.Int.Input("count", default=2, min=1, max=5),
                IO.String.Input("segment_1", default=""),
                IO.String.Input("segment_2", default=""),
                IO.String.Input("segment_3", default=""),
                IO.String.Input("segment_4", default=""),
                IO.String.Input("segment_5", default=""),
            ],
            outputs=[IO.String.Output("path", display_name="path")],
        ))

    @classmethod
    async def execute(
        cls,
        count,
        segment_1,
        segment_2,
        segment_3,
        segment_4,
        segment_5,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "join_path",
            count=count,
            segment_1=segment_1,
            segment_2=segment_2,
            segment_3=segment_3,
            segment_4=segment_4,
            segment_5=segment_5,
        )


__all__ = ["WuddV3PathJoiner"]

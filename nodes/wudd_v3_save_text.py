from __future__ import annotations

from ._base import *


class WuddV3SaveText(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddSaveText

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3SaveText",
            display_name="Wudd V3 Save Text",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Combo.Input("root_dir", options=["output", "input", "temp"], default="output"),
                IO.String.Input("file", default="Wudd_Text.txt"),
                IO.Combo.Input("append", options=["overwrite", "append", "new_only"], default="overwrite"),
                IO.Boolean.Input("insert", default=False),
            ],
            outputs=[IO.String.Output("path", display_name="path")],
            is_output_node=True,
        )

    @classmethod
    async def execute(
        cls,
        text,
        root_dir="output",
        file="Wudd_Text.txt",
        append="overwrite",
        insert=False,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "save_text",
            text=text,
            root_dir=root_dir,
            file=file,
            append=append,
            insert=insert,
        )


__all__ = ["WuddV3SaveText"]

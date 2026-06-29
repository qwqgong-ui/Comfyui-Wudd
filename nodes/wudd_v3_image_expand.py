from __future__ import annotations

from ._base import *


class WuddV3ImageExpand(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddImageExpand

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ImageExpand",
            display_name="Wudd V3 Image Expand",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Image.Input("image"),
                IO.Combo.Input("direction", options=["right", "down", "left", "up"], default="right"),
                IO.Int.Input("count", default=1, min=1, max=16, step=1),
                IO.DynamicCombo.Input(
                    "mode",
                    options=[
                        IO.DynamicCombo.Option(
                            "checkerboard",
                            [IO.Int.Input("tile_size", default=16, min=4, max=128, step=4)],
                        ),
                        IO.DynamicCombo.Option(
                            "fill_color",
                            [IO.String.Input("fill_color", default="#808080")],
                        ),
                    ],
                ),
            ],
            outputs=[
                IO.Image.Output("image", display_name="image"),
                IO.Int.Output("width", display_name="width"),
                IO.Int.Output("height", display_name="height"),
            ],
        )

    @classmethod
    async def execute(cls, image, direction, count, mode=None) -> IO.NodeOutput:
        selected_mode, mode_inputs = _dynamic_value(mode, "mode", "checkerboard")
        return await cls._run_backend(
            "expand",
            image=image,
            direction=direction,
            count=count,
            mode=selected_mode,
            fill_color=mode_inputs.get("fill_color", "#808080"),
            tile_size=mode_inputs.get("tile_size", 16),
        )


__all__ = ["WuddV3ImageExpand"]

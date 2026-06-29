from __future__ import annotations

from ._base import *


class WuddV3DropAlpha(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddDropAlpha

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3DropAlpha",
            display_name="Wudd V3 Drop Alpha",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Image.Input("image"),
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
                IO.Boolean.Input("auto_crop", default=False),
                IO.Int.Input("padding", default=0, min=0, max=2048),
                IO.Mask.Input("mask", optional=True),
            ],
            outputs=[IO.Image.Output("image", display_name="image")],
        )

    @classmethod
    async def execute(cls, image, mode=None, auto_crop=False, padding=0, mask=None) -> IO.NodeOutput:
        selected_mode, mode_inputs = _dynamic_value(mode, "mode", "checkerboard")
        return await cls._run_backend(
            "drop_alpha",
            image=image,
            mode=selected_mode,
            fill_color=mode_inputs.get("fill_color", "#808080"),
            tile_size=mode_inputs.get("tile_size", 16),
            auto_crop=auto_crop,
            padding=padding,
            mask=mask,
        )


__all__ = ["WuddV3DropAlpha"]

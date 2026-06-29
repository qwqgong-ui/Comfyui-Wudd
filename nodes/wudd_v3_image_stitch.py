from __future__ import annotations

from ._base import *


class WuddV3ImageStitch(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddImageStitch

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ImageStitch",
            display_name="Wudd V3 Image Stitch",
            category=WUDD_V3_CATEGORY,
            inputs=[
                _image_autogrow("images", IMAGE_16_NAMES, min_count=1),
                IO.Combo.Input("direction", options=["right", "down", "left", "up"], default="right"),
                IO.Int.Input("gap", default=0, min=0, max=256, step=1),
            ],
            outputs=[IO.Image.Output("image", display_name="image")],
        )

    @classmethod
    async def execute(cls, images: IO.Autogrow.Type, direction="right", gap=0) -> IO.NodeOutput:
        items = _numbered_items(images, "image_")
        if not items:
            raise ValueError("At least one image input is required.")
        image_1 = items[0][1]
        rest = {name: value for name, value in items[1:]}
        return await cls._run_backend(
            "stitch",
            image_1=image_1,
            direction=direction,
            gap=gap,
            input_count=len(items),
            **rest,
        )


__all__ = ["WuddV3ImageStitch"]

from __future__ import annotations

from .._base import *


class WuddV3EdgePad(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddEdgePad

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3EdgePad",
            display_name="Wudd V3 Edge Pad",
            category=IMAGE_CATEGORY,
            inputs=[
                _image_autogrow("images", IMAGE_16_NAMES, min_count=1),
                IO.Int.Input("pad_px", default=100, min=10, max=500, step=1),
                IO.Float.Input("blend_pct", default=3.0, min=0.5, max=20.0, step=0.5),
                IO.Float.Input("pad_sigma", default=30.0, min=1.0, max=200.0, step=1.0),
                IO.Float.Input("blend_sigma", default=12.0, min=1.0, max=80.0, step=0.5),
                IO.Float.Input("chamfer_pct", default=20.0, min=0.0, max=80.0, step=1.0),
            ],
            outputs=[
                IO.Image.Output(f"image_{i}", display_name=f"image_{i}")
                for i in range(1, WuddEdgePad.MAX_INPUTS + 1)
            ],
        ))

    @classmethod
    async def execute(
        cls,
        images: IO.Autogrow.Type,
        pad_px,
        blend_pct,
        pad_sigma,
        blend_sigma,
        chamfer_pct,
    ) -> IO.NodeOutput:
        image_1, rest = _first_and_rest(images, "image_")
        return await cls._run_backend(
            "pad_edges",
            image_1=image_1,
            pad_px=pad_px,
            blend_pct=blend_pct,
            pad_sigma=pad_sigma,
            blend_sigma=blend_sigma,
            chamfer_pct=chamfer_pct,
            **rest,
        )


__all__ = ["WuddV3EdgePad"]

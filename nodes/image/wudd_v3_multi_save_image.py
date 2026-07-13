from __future__ import annotations

from .._base import *


class WuddV3MultiSaveImage(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddMultiSaveImage

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3MultiSaveImage",
            display_name="Wudd V3 Multi Save",
            category=IMAGE_CATEGORY,
            inputs=[
                _image_autogrow("images", IMAGE_100_NAMES, min_count=1),
                IO.String.Input("filename_prefix", default="Wudd_Img"),
                IO.Combo.Input("save_mode", options=["append", "overwrite"], default="append"),
                IO.DynamicCombo.Input(
                    "extension",
                    options=[
                        IO.DynamicCombo.Option("png", []),
                        IO.DynamicCombo.Option(
                            "jpegli",
                            [
                                IO.Int.Input("quality", default=90, min=1, max=100),
                                IO.Boolean.Input("progressive", default=True),
                                IO.Boolean.Input("enable_xyb", default=False),
                                IO.Combo.Input(
                                    "chroma_subsampling",
                                    options=["444", "440", "422", "420"],
                                    default="444",
                                ),
                            ],
                        ),
                    ],
                ),
            ],
            outputs=[],
            hidden=[IO.Hidden.prompt, IO.Hidden.extra_pnginfo],
            is_output_node=True,
        ))

    @classmethod
    async def execute(
        cls,
        images: IO.Autogrow.Type,
        filename_prefix="Wudd_Img",
        save_mode="append",
        extension=None,
    ) -> IO.NodeOutput:
        image_1, rest = _first_and_rest(images, "image_")
        selected_extension, extension_inputs = _dynamic_value(extension, "extension", "png")
        return await cls._run_backend(
            "save_images",
            image_1=image_1,
            filename_prefix=filename_prefix,
            save_mode=save_mode,
            extension=selected_extension,
            quality=extension_inputs.get("quality", 90),
            progressive=extension_inputs.get("progressive", True),
            enable_xyb=extension_inputs.get("enable_xyb", False),
            chroma_subsampling=extension_inputs.get("chroma_subsampling", "444"),
            prompt=cls.hidden.prompt,
            extra_pnginfo=cls.hidden.extra_pnginfo,
            **rest,
        )


__all__ = ["WuddV3MultiSaveImage"]

from __future__ import annotations

from .._base import *


class WuddV3ImageListImporter(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddImageListImporter

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3ImageListImporter",
            display_name="Wudd V3 Image List Importer",
            category=IMAGE_CATEGORY,
            inputs=[
                IO.DynamicCombo.Input(
                    "mode",
                    options=[
                        IO.DynamicCombo.Option(
                            "files",
                            [
                                IO.Int.Input(
                                    "image_count",
                                    default=1,
                                    min=1,
                                    max=WuddImageListImporter.MAX_IMAGES,
                                    step=1,
                                ),
                                *_image_file_inputs(WuddImageListImporter.MAX_IMAGES),
                            ],
                        ),
                        IO.DynamicCombo.Option(
                            "folder",
                            [
                                IO.Int.Input(
                                    "image_count",
                                    default=1,
                                    min=1,
                                    max=WuddImageListImporter.MAX_IMAGES,
                                    step=1,
                                ),
                                IO.String.Input(
                                    "folder_path",
                                    default="",
                                    multiline=False,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
            outputs=[
                IO.Image.Output(f"image_{i}", display_name=f"image_{i}")
                for i in range(1, WuddImageListImporter.MAX_IMAGES + 1)
            ],
        ))

    @classmethod
    def fingerprint_inputs(cls, mode=None, **kwargs):
        selected_mode, mode_inputs = _dynamic_value(mode, "mode", "files")
        params = {**mode_inputs, **kwargs}
        image_count = params.get("image_count", 1)
        folder_path = params.get("folder_path", "")
        image_kwargs = {
            key: value
            for key, value in params.items()
            if _is_numbered_name(key, "image_")
        }
        return cls.BACKEND_CLS.IS_CHANGED(
            image_count,
            mode=selected_mode,
            folder_path=folder_path,
            **image_kwargs,
        )

    @classmethod
    async def execute(cls, mode=None) -> IO.NodeOutput:
        selected_mode, mode_inputs = _dynamic_value(mode, "mode", "files")
        image_count = mode_inputs.get("image_count", 1)
        folder_path = mode_inputs.get("folder_path", "")
        image_kwargs = {
            key: value
            for key, value in mode_inputs.items()
            if _is_numbered_name(key, "image_")
        }
        return await cls._run_backend(
            "import_images",
            image_count=image_count,
            mode=selected_mode,
            folder_path=folder_path,
            **image_kwargs,
        )


__all__ = ["WuddV3ImageListImporter"]

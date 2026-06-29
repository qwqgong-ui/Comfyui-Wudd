from __future__ import annotations

from ._base import *


class WuddV3ConcatVideos(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddConcatVideos

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ConcatVideos",
            display_name="Wudd V3 Concat Videos",
            category=WUDD_V3_CATEGORY,
            inputs=[
                _video_autogrow("videos", VIDEO_100_NAMES, min_count=2),
                IO.Combo.Input(
                    "resize_mode",
                    options=["fit_to_first", "stretch_to_first"],
                    default="fit_to_first",
                ),
                IO.Combo.Input("audio_mode", options=["keep", "none"], default="keep"),
            ],
            outputs=[IO.Video.Output("video", display_name="video")],
        )

    @classmethod
    async def execute(
        cls,
        videos: IO.Autogrow.Type,
        resize_mode="fit_to_first",
        audio_mode="keep",
    ) -> IO.NodeOutput:
        items = _numbered_items(videos, "video_")
        if not items:
            raise ValueError("At least one video input is required.")
        video_1 = items[0][1]
        video_2 = items[1][1] if len(items) > 1 else None
        rest = {name: value for name, value in items[2:]}
        return await cls._run_backend(
            "concat_videos",
            video_1=video_1,
            video_2=video_2,
            resize_mode=resize_mode,
            audio_mode=audio_mode,
            **rest,
        )


__all__ = ["WuddV3ConcatVideos"]

from __future__ import annotations

from .._base import *


class WuddV3SaveVideo(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddSaveVideo

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3SaveVideo",
            display_name="Wudd V3 Save Video",
            category=VIDEO_CATEGORY,
            inputs=[
                _video_autogrow("videos", VIDEO_100_NAMES, min_count=1),
                IO.String.Input("filename_prefix", default="Wudd_Video"),
                IO.Combo.Input("save_mode", options=["append", "overwrite"], default="append"),
                IO.Combo.Input("codec", options=["av1", "h265"], default="av1"),
                IO.Combo.Input("encoder", options=["cpu", "nvidia", "intel", "amd"], default="cpu"),
                IO.Combo.Input("container", options=["mp4", "mkv"], default="mp4"),
                IO.Int.Input("crf", default=28, min=0, max=51, step=1),
                IO.Combo.Input("preset", options=["fast", "medium", "slow"], default="medium"),
                IO.Combo.Input("audio_mode", options=["copy", "aac", "none"], default="copy"),
            ],
            outputs=[],
            hidden=[IO.Hidden.prompt, IO.Hidden.extra_pnginfo],
            is_output_node=True,
        ))

    @classmethod
    async def execute(
        cls,
        videos: IO.Autogrow.Type,
        filename_prefix="Wudd_Video",
        save_mode="append",
        codec="av1",
        encoder="cpu",
        container="mp4",
        crf=28,
        preset="medium",
        audio_mode="copy",
    ) -> IO.NodeOutput:
        video_1, rest = _first_and_rest(videos, "video_")
        return await cls._run_backend(
            "save_videos",
            video_1=video_1,
            filename_prefix=filename_prefix,
            save_mode=save_mode,
            codec=codec,
            encoder=encoder,
            container=container,
            crf=crf,
            preset=preset,
            audio_mode=audio_mode,
            prompt=cls.hidden.prompt,
            extra_pnginfo=cls.hidden.extra_pnginfo,
            **rest,
        )


__all__ = ["WuddV3SaveVideo"]

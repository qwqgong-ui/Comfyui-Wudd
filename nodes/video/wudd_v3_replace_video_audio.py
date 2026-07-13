from __future__ import annotations

from .._base import *


class WuddV3ReplaceVideoAudio(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddReplaceVideoAudio

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3ReplaceVideoAudio",
            display_name="Wudd V3 Replace Video Audio",
            category=VIDEO_CATEGORY,
            inputs=[
                IO.Video.Input("video"),
                IO.Audio.Input("audio"),
                IO.Combo.Input("output_format", options=["mp4", "mkv", "mov"], default="mp4"),
                IO.Combo.Input("audio_bitrate", options=["128k", "192k", "256k", "320k"], default="192k"),
                IO.Combo.Input(
                    "end_mode",
                    options=["keep_video_length", "shortest"],
                    default="keep_video_length",
                ),
            ],
            outputs=[IO.Video.Output("video", display_name="video")],
        ))

    @classmethod
    async def execute(
        cls,
        video,
        audio,
        output_format="mp4",
        audio_bitrate="192k",
        end_mode="keep_video_length",
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "replace_audio",
            video=video,
            audio=audio,
            output_format=output_format,
            audio_bitrate=audio_bitrate,
            end_mode=end_mode,
        )


__all__ = ["WuddV3ReplaceVideoAudio"]

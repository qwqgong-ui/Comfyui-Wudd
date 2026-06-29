from __future__ import annotations

from ._base import *


class WuddV3VideoAudioExtractor(_FingerprintBackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddVideoAudioExtractor

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3VideoAudioExtractor",
            display_name="Wudd V3 Extract Audio From Video",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Video.Input("video"),
                IO.Int.Input("audio_stream_index", default=0, min=0, max=16, step=1),
            ],
            outputs=[
                IO.Audio.Output("audio", display_name="audio"),
                IO.Int.Output("sample_rate", display_name="sample_rate"),
                IO.Float.Output("duration_seconds", display_name="duration_seconds"),
            ],
        )

    @classmethod
    async def execute(cls, video, audio_stream_index=0) -> IO.NodeOutput:
        return await cls._run_backend(
            "extract_audio",
            video=video,
            audio_stream_index=audio_stream_index,
        )


__all__ = ["WuddV3VideoAudioExtractor"]

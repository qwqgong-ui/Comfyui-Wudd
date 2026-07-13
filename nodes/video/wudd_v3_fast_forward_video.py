from __future__ import annotations

from .._base import *


class WuddV3FastForwardVideo(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddFastForwardVideo

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3FastForwardVideo",
            display_name="Wudd V3 Video Fast Forward",
            category=VIDEO_CATEGORY,
            inputs=[
                IO.Video.Input("video"),
                IO.DynamicCombo.Input(
                    "mode",
                    options=[
                        IO.DynamicCombo.Option(
                            "speed_multiplier",
                            [
                                IO.Float.Input(
                                    "speed_multiplier",
                                    default=2.0,
                                    min=0.01,
                                    max=100.0,
                                    step=0.01,
                                ),
                            ],
                        ),
                        IO.DynamicCombo.Option(
                            "target_seconds",
                            [
                                IO.Float.Input(
                                    "target_seconds",
                                    default=5.0,
                                    min=0.001,
                                    max=86400.0,
                                    step=0.001,
                                ),
                            ],
                        ),
                    ],
                ),
                IO.Combo.Input("audio_mode", options=["keep", "none"], default="keep"),
            ],
            outputs=[IO.Video.Output("video", display_name="video")],
        ))

    @classmethod
    async def execute(cls, video, mode=None, audio_mode="keep") -> IO.NodeOutput:
        selected_mode, mode_inputs = _dynamic_value(mode, "mode", "speed_multiplier")
        return await cls._run_backend(
            "fast_forward_video",
            video=video,
            mode=selected_mode,
            speed_multiplier=mode_inputs.get("speed_multiplier", 2.0),
            target_seconds=mode_inputs.get("target_seconds", 5.0),
            audio_mode=audio_mode,
        )


__all__ = ["WuddV3FastForwardVideo"]

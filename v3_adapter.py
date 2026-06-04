"""
Native V3 node definitions for ComfyUI-Wudd-V3.

The V3 package keeps WuddV3* node ids so it can live beside the original V1
package, but schemas are declared directly with the Comfy V3 API. Heavy image,
video, audio, and API implementation code is reused from the local nodes_* modules
to avoid copying the same processing logic into two places.
"""

from __future__ import annotations

import inspect
from typing import Any

from comfy_api.latest import IO, ComfyExtension

from .nodes_api import (
    CLAUDE_TEXT_MODELS,
    EXTENDED_ASPECT_RATIOS,
    GEMINI_IMAGE_MODELS,
    GEMINI_IMAGE_SIZES,
    GEMINI_TEXT_MODELS,
    GPT_IMAGE_SIZES,
    IMAGE_RESPONSE_MODALITIES,
    MAX_IMAGE_NODE_INPUTS,
    MAX_TEXT_IMAGE_INPUTS,
    OPENAI_GPT_IMAGE_MODELS,
    OPENAI_GPT_TEXT_MODELS,
    OPENROUTER_BASE_URL,
    REASONING_EFFORTS,
    STANDARD_ASPECT_RATIOS,
    TEXT_RESPONSE_FORMATS,
    WuddOpenRouterClaudeText,
    WuddOpenRouterGPTImage,
    WuddOpenRouterGPTText,
    WuddOpenRouterGeminiImage,
    WuddOpenRouterGeminiText,
)
from .nodes_audio import WuddReplaceVideoAudio, WuddVideoAudioExtractor
from .nodes_group import WuddGroupSwitch
from .nodes_image import (
    WuddDropAlpha,
    WuddEdgePad,
    WuddImageExpand,
    WuddImageListImporter,
    WuddImageStitch,
    WuddMultiSaveImage,
)
from .nodes_text import (
    WuddMultiTextSplitter,
    WuddPathJoiner,
    WuddPromptListFromText,
    WuddTextSplitter,
)
from .nodes_video import WuddConcatVideos, WuddFastForwardVideo, WuddSaveVideo


WUDD_V3_CATEGORY = "Wudd Nodes V3"
OPENROUTER_TEXT_CATEGORY = f"{WUDD_V3_CATEGORY}/OpenRouter/Text"
OPENROUTER_IMAGE_CATEGORY = f"{WUDD_V3_CATEGORY}/OpenRouter/Image"

IMAGE_16_NAMES = [f"image_{i}" for i in range(1, 17)]
IMAGE_50_NAMES = [f"image_{i}" for i in range(1, 51)]
IMAGE_100_NAMES = [f"image_{i}" for i in range(1, 101)]
VIDEO_100_NAMES = [f"video_{i}" for i in range(1, 101)]

_BACKEND_CACHE: dict[type, Any] = {}


def _to_node_output(result: Any) -> IO.NodeOutput:
    if isinstance(result, IO.NodeOutput):
        return result
    if result is None:
        return IO.NodeOutput()
    if isinstance(result, dict):
        return IO.NodeOutput.from_dict(result)
    if isinstance(result, tuple):
        return IO.NodeOutput(*result)
    return IO.NodeOutput(result)


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


def _numbered_index(name: str, prefix: str) -> int:
    suffix = str(name or "")[len(prefix) :]
    try:
        return int(suffix)
    except ValueError:
        return 10**9


def _is_numbered_name(name: str, prefix: str) -> bool:
    value = str(name or "")
    return value.startswith(prefix) and value[len(prefix) :].isdigit()


def _numbered_items(values: dict[str, Any] | None, prefix: str) -> list[tuple[str, Any]]:
    if not values:
        return []
    items = [
        (name, value)
        for name, value in values.items()
        if _is_numbered_name(name, prefix) and value is not None
    ]
    items.sort(key=lambda item: _numbered_index(item[0], prefix))
    return items


def _first_and_rest(values: dict[str, Any] | None, prefix: str) -> tuple[Any, dict[str, Any]]:
    items = _numbered_items(values, prefix)
    if not items:
        raise ValueError(f"At least one {prefix.rstrip('_')} input is required.")
    return items[0][1], {name: value for name, value in items[1:]}


def _numbered_kwargs(values: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    return {name: value for name, value in _numbered_items(values, prefix)}


def _image_autogrow(
    input_id: str,
    names: list[str],
    *,
    min_count: int,
    optional_items: bool = False,
) -> IO.Autogrow.Input:
    return IO.Autogrow.Input(
        input_id,
        template=IO.Autogrow.TemplateNames(
            IO.Image.Input("image", optional=optional_items),
            names=names,
            min=min_count,
        ),
        optional=optional_items,
    )


def _video_autogrow(input_id: str, names: list[str], *, min_count: int) -> IO.Autogrow.Input:
    return IO.Autogrow.Input(
        input_id,
        template=IO.Autogrow.TemplateNames(IO.Video.Input("video"), names=names, min=min_count),
    )


def _dynamic_value(value: dict[str, Any] | str | None, key: str, default: str) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        selected = value.get(key, default)
        return selected, value
    return value or default, {}


def _files_for_upload() -> list[str]:
    files = WuddImageListImporter._list_input_files()
    return files or ["none"]


def _image_file_inputs(max_images: int) -> list[Any]:
    files = _files_for_upload()
    default = files[0] if files else "none"
    return [
        IO.Combo.Input(
            f"image_{i}",
            options=files,
            default=default,
            upload=IO.UploadType.image,
        )
        for i in range(1, max_images + 1)
    ]


def _api_runtime_inputs() -> list[Any]:
    return [
        IO.String.Input("base_url", default=OPENROUTER_BASE_URL, advanced=True),
        IO.Int.Input("timeout_seconds", default=300, min=5, max=3600, step=1, advanced=True),
        IO.Boolean.Input("verify_ssl", default=True, advanced=True),
    ]


def _system_and_extra_inputs() -> list[Any]:
    return [
        IO.String.Input("system_prompt", default="", multiline=True),
        IO.String.Input("extra_body_json", default="", multiline=True, advanced=True),
    ]


def _seed_input() -> IO.Int.Input:
    return IO.Int.Input(
        "seed",
        default=0,
        min=0,
        max=2147483647,
        step=1,
        control_after_generate=True,
    )


class _BackendNode:
    BACKEND_CLS: type | None = None

    @classmethod
    def _backend(cls):
        backend_cls = cls.BACKEND_CLS
        if backend_cls is None:
            raise RuntimeError(f"{cls.__name__} does not define BACKEND_CLS.")
        backend = _BACKEND_CACHE.get(backend_cls)
        if backend is None:
            backend = backend_cls()
            _BACKEND_CACHE[backend_cls] = backend
        return backend

    @classmethod
    async def _run_backend(cls, method_name: str, **kwargs) -> IO.NodeOutput:
        method = getattr(cls._backend(), method_name)
        result = await _maybe_await(method(**kwargs))
        return _to_node_output(result)


class _FingerprintBackendNode(_BackendNode):
    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        if hasattr(cls.BACKEND_CLS, "IS_CHANGED"):
            return cls.BACKEND_CLS.IS_CHANGED(**kwargs)
        return False


class WuddV3MultiSaveImage(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddMultiSaveImage

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3MultiSaveImage",
            display_name="Wudd V3 Multi Save",
            category=WUDD_V3_CATEGORY,
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
        )

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


class WuddV3SaveVideo(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddSaveVideo

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3SaveVideo",
            display_name="Wudd V3 Save Video",
            category=WUDD_V3_CATEGORY,
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
        )

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


class WuddV3FastForwardVideo(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddFastForwardVideo

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3FastForwardVideo",
            display_name="Wudd V3 Video Fast Forward",
            category=WUDD_V3_CATEGORY,
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
        )

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


class WuddV3ReplaceVideoAudio(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddReplaceVideoAudio

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ReplaceVideoAudio",
            display_name="Wudd V3 Replace Video Audio",
            category=WUDD_V3_CATEGORY,
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
        )

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


class WuddV3TextSplitter(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddTextSplitter

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3TextSplitter",
            display_name="Wudd V3 Text Splitter",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Int.Input("index", default=0, min=0, max=99999),
                IO.Boolean.Input("skip_empty", default=False),
            ],
            outputs=[IO.String.Output("text", display_name="text")],
        )

    @classmethod
    async def execute(cls, text, index, skip_empty=False) -> IO.NodeOutput:
        return await cls._run_backend("split_text", text=text, index=index, skip_empty=skip_empty)


class WuddV3MultiTextSplitter(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddMultiTextSplitter

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3MultiTextSplitter",
            display_name="Wudd V3 Multi Text Splitter",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Int.Input("count", default=2, min=1, max=WuddMultiTextSplitter.MAX_OUTPUTS),
                IO.Boolean.Input("skip_empty", default=False),
            ],
            outputs=[
                IO.String.Output(f"line_{i}", display_name=f"line_{i}")
                for i in range(WuddMultiTextSplitter.MAX_OUTPUTS)
            ],
        )

    @classmethod
    async def execute(cls, text, count, skip_empty=False) -> IO.NodeOutput:
        return await cls._run_backend("split_text", text=text, count=count, skip_empty=skip_empty)


class WuddV3PromptListFromText(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddPromptListFromText

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3PromptListFromText",
            display_name="Wudd V3 Prompt List From Text",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.String.Input("text", default="", multiline=True),
                IO.Boolean.Input("skip_empty", default=True),
                IO.Boolean.Input("strip_numbering", default=True),
            ],
            outputs=[
                IO.String.Output("prompts", display_name="prompts", is_output_list=True),
                IO.Int.Output("count", display_name="count"),
            ],
        )

    @classmethod
    async def execute(cls, text, skip_empty=True, strip_numbering=True) -> IO.NodeOutput:
        return await cls._run_backend(
            "to_list",
            text=text,
            skip_empty=skip_empty,
            strip_numbering=strip_numbering,
        )


class WuddV3PathJoiner(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddPathJoiner

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3PathJoiner",
            display_name="Wudd V3 Path Joiner",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Int.Input("count", default=2, min=1, max=5),
                IO.String.Input("segment_1", default=""),
                IO.String.Input("segment_2", default=""),
                IO.String.Input("segment_3", default=""),
                IO.String.Input("segment_4", default=""),
                IO.String.Input("segment_5", default=""),
            ],
            outputs=[IO.String.Output("path", display_name="path")],
        )

    @classmethod
    async def execute(
        cls,
        count,
        segment_1,
        segment_2,
        segment_3,
        segment_4,
        segment_5,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "join_path",
            count=count,
            segment_1=segment_1,
            segment_2=segment_2,
            segment_3=segment_3,
            segment_4=segment_4,
            segment_5=segment_5,
        )


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


class WuddV3ImageExpand(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddImageExpand

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ImageExpand",
            display_name="Wudd V3 Image Expand",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Image.Input("image"),
                IO.Combo.Input("direction", options=["right", "down", "left", "up"], default="right"),
                IO.Int.Input("count", default=1, min=1, max=16, step=1),
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
            ],
            outputs=[
                IO.Image.Output("image", display_name="image"),
                IO.Int.Output("width", display_name="width"),
                IO.Int.Output("height", display_name="height"),
            ],
        )

    @classmethod
    async def execute(cls, image, direction, count, mode=None) -> IO.NodeOutput:
        selected_mode, mode_inputs = _dynamic_value(mode, "mode", "checkerboard")
        return await cls._run_backend(
            "expand",
            image=image,
            direction=direction,
            count=count,
            mode=selected_mode,
            fill_color=mode_inputs.get("fill_color", "#808080"),
            tile_size=mode_inputs.get("tile_size", 16),
        )


class WuddV3EdgePad(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddEdgePad

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3EdgePad",
            display_name="Wudd V3 Edge Pad",
            category=WUDD_V3_CATEGORY,
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
        )

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


class WuddV3ImageListImporter(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddImageListImporter

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ImageListImporter",
            display_name="Wudd V3 Image List Importer",
            category=WUDD_V3_CATEGORY,
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
        )

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


class WuddV3GroupSwitch(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddGroupSwitch

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3GroupSwitch",
            display_name="Wudd V3 Group Switch",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Boolean.Input("enabled", default=True),
                IO.String.Input("group_name", default="", multiline=False),
                IO.Combo.Input("off_mode", options=["mute", "bypass"], default="mute"),
            ],
            outputs=[
                IO.Boolean.Output("enabled", display_name="enabled"),
                IO.String.Output("group_name", display_name="group_name"),
            ],
        )

    @classmethod
    async def execute(cls, enabled, group_name="", off_mode="mute") -> IO.NodeOutput:
        return await cls._run_backend(
            "switch_group",
            enabled=enabled,
            group_name=group_name,
            off_mode=off_mode,
        )


class _OpenRouterV3Node(_FingerprintBackendNode):
    @classmethod
    def _api_image_kwargs(cls, images: IO.Autogrow.Type | None) -> dict[str, Any]:
        return _numbered_kwargs(images, "image_")


class WuddV3OpenRouterGPTText(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterGPTText

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3OpenRouterGPTText",
            display_name="Wudd V3 OpenRouter GPT Text",
            category=OPENROUTER_TEXT_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input("model", options=OPENAI_GPT_TEXT_MODELS, default="openai/gpt-5.5"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                IO.Boolean.Input("include_reasoning", default=False),
                IO.Combo.Input("response_format", options=TEXT_RESPONSE_FORMATS, default="text"),
                _seed_input(),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                _image_autogrow(
                    "images",
                    IMAGE_16_NAMES[:MAX_TEXT_IMAGE_INPUTS],
                    min_count=1,
                    optional_items=True,
                ),
            ],
            outputs=[
                IO.String.Output("text", display_name="text"),
                IO.String.Output("reasoning", display_name="reasoning"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        prompt,
        api_key,
        model,
        max_tokens,
        reasoning_effort,
        include_reasoning,
        response_format,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        images=None,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            include_reasoning=include_reasoning,
            response_format=response_format,
            seed=seed,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            **cls._api_image_kwargs(images),
        )


class WuddV3OpenRouterClaudeText(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterClaudeText

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3OpenRouterClaudeText",
            display_name="Wudd V3 OpenRouter Claude Text",
            category=OPENROUTER_TEXT_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input("model", options=CLAUDE_TEXT_MODELS, default="anthropic/claude-sonnet-4.6"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Float.Input("temperature", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Float.Input("top_p", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Int.Input("top_k", default=0, min=0, max=1000, step=1),
                IO.Combo.Input(
                    "verbosity",
                    options=["none", "low", "medium", "high", "xhigh", "max"],
                    default="none",
                ),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                IO.Boolean.Input("include_reasoning", default=False),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                IO.String.Input("stop_sequences", default="", multiline=True, advanced=True),
            ],
            outputs=[
                IO.String.Output("text", display_name="text"),
                IO.String.Output("reasoning", display_name="reasoning"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        prompt,
        api_key,
        model,
        max_tokens,
        temperature,
        top_p,
        top_k,
        verbosity,
        reasoning_effort,
        include_reasoning,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        stop_sequences="",
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            verbosity=verbosity,
            reasoning_effort=reasoning_effort,
            include_reasoning=include_reasoning,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            stop_sequences=stop_sequences,
        )


class WuddV3OpenRouterGeminiText(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterGeminiText

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3OpenRouterGeminiText",
            display_name="Wudd V3 OpenRouter Gemini Text",
            category=OPENROUTER_TEXT_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input(
                    "model",
                    options=GEMINI_TEXT_MODELS,
                    default="google/gemini-3.1-pro-preview",
                ),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Float.Input("temperature", default=1.0, min=0.0, max=2.0, step=0.01),
                IO.Float.Input("top_p", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                IO.Boolean.Input("include_reasoning", default=False),
                IO.Combo.Input("response_format", options=TEXT_RESPONSE_FORMATS, default="text"),
                _seed_input(),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                IO.String.Input("stop_sequences", default="", multiline=True, advanced=True),
                _image_autogrow(
                    "images",
                    IMAGE_16_NAMES[:MAX_TEXT_IMAGE_INPUTS],
                    min_count=1,
                    optional_items=True,
                ),
            ],
            outputs=[
                IO.String.Output("text", display_name="text"),
                IO.String.Output("reasoning", display_name="reasoning"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        prompt,
        api_key,
        model,
        max_tokens,
        temperature,
        top_p,
        reasoning_effort,
        include_reasoning,
        response_format,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        stop_sequences="",
        images=None,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            include_reasoning=include_reasoning,
            response_format=response_format,
            seed=seed,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            stop_sequences=stop_sequences,
            **cls._api_image_kwargs(images),
        )


class WuddV3OpenRouterGPTImage(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterGPTImage

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3OpenRouterGPTImage",
            display_name="Wudd V3 OpenRouter GPT Image",
            category=OPENROUTER_IMAGE_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input(
                    "model",
                    options=OPENAI_GPT_IMAGE_MODELS,
                    default="openai/gpt-5.4-image-2",
                ),
                IO.Combo.Input(
                    "response_modalities",
                    options=IMAGE_RESPONSE_MODALITIES,
                    default="IMAGE+TEXT",
                ),
                IO.Combo.Input("aspect_ratio", options=STANDARD_ASPECT_RATIOS, default="auto"),
                IO.Combo.Input("image_size", options=GPT_IMAGE_SIZES, default="auto"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                _seed_input(),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                _image_autogrow(
                    "images",
                    IMAGE_16_NAMES[:MAX_IMAGE_NODE_INPUTS],
                    min_count=1,
                    optional_items=True,
                ),
            ],
            outputs=[
                IO.Image.Output("image", display_name="image"),
                IO.String.Output("text", display_name="text"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        prompt,
        api_key,
        model,
        response_modalities,
        aspect_ratio,
        image_size,
        max_tokens,
        reasoning_effort,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        images=None,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            response_modalities=response_modalities,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            seed=seed,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            **cls._api_image_kwargs(images),
        )


class WuddV3OpenRouterGeminiImage(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterGeminiImage

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3OpenRouterGeminiImage",
            display_name="Wudd V3 OpenRouter Gemini Image",
            category=OPENROUTER_IMAGE_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input(
                    "model",
                    options=GEMINI_IMAGE_MODELS,
                    default="google/gemini-3.1-flash-image-preview",
                ),
                IO.Combo.Input(
                    "response_modalities",
                    options=IMAGE_RESPONSE_MODALITIES,
                    default="IMAGE+TEXT",
                ),
                IO.Combo.Input("aspect_ratio", options=EXTENDED_ASPECT_RATIOS, default="auto"),
                IO.Combo.Input("image_size", options=GEMINI_IMAGE_SIZES, default="auto"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Float.Input("temperature", default=1.0, min=0.0, max=2.0, step=0.01),
                IO.Float.Input("top_p", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                _seed_input(),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                _image_autogrow(
                    "images",
                    IMAGE_16_NAMES[:MAX_IMAGE_NODE_INPUTS],
                    min_count=1,
                    optional_items=True,
                ),
            ],
            outputs=[
                IO.Image.Output("image", display_name="image"),
                IO.String.Output("text", display_name="text"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        prompt,
        api_key,
        model,
        response_modalities,
        aspect_ratio,
        image_size,
        max_tokens,
        temperature,
        top_p,
        reasoning_effort,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        images=None,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            response_modalities=response_modalities,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            seed=seed,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            **cls._api_image_kwargs(images),
        )


WUDD_V3_NODE_CLASSES = {
    "WuddV3MultiSaveImage": WuddV3MultiSaveImage,
    "WuddV3SaveVideo": WuddV3SaveVideo,
    "WuddV3FastForwardVideo": WuddV3FastForwardVideo,
    "WuddV3ConcatVideos": WuddV3ConcatVideos,
    "WuddV3TextSplitter": WuddV3TextSplitter,
    "WuddV3MultiTextSplitter": WuddV3MultiTextSplitter,
    "WuddV3PromptListFromText": WuddV3PromptListFromText,
    "WuddV3DropAlpha": WuddV3DropAlpha,
    "WuddV3ImageExpand": WuddV3ImageExpand,
    "WuddV3EdgePad": WuddV3EdgePad,
    "WuddV3ImageListImporter": WuddV3ImageListImporter,
    "WuddV3ImageStitch": WuddV3ImageStitch,
    "WuddV3PathJoiner": WuddV3PathJoiner,
    "WuddV3VideoAudioExtractor": WuddV3VideoAudioExtractor,
    "WuddV3ReplaceVideoAudio": WuddV3ReplaceVideoAudio,
    "WuddV3OpenRouterGPTText": WuddV3OpenRouterGPTText,
    "WuddV3OpenRouterClaudeText": WuddV3OpenRouterClaudeText,
    "WuddV3OpenRouterGeminiText": WuddV3OpenRouterGeminiText,
    "WuddV3OpenRouterGPTImage": WuddV3OpenRouterGPTImage,
    "WuddV3OpenRouterGeminiImage": WuddV3OpenRouterGeminiImage,
    "WuddV3GroupSwitch": WuddV3GroupSwitch,
}


class WuddV3Extension(ComfyExtension):
    async def get_node_list(self) -> list[type[IO.ComfyNode]]:
        return list(WUDD_V3_NODE_CLASSES.values())


async def comfy_entrypoint() -> WuddV3Extension:
    return WuddV3Extension()

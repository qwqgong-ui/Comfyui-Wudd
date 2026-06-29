"""Shared helpers and backend bindings for V3 node schema modules."""

from __future__ import annotations

import inspect
from typing import Any

from comfy_api.latest import IO

from ..core.openrouter_common import (
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
)
from ..core.openrouter_claude_text import WuddOpenRouterClaudeText
from ..core.openrouter_gemini_image import WuddOpenRouterGeminiImage
from ..core.openrouter_gemini_text import WuddOpenRouterGeminiText
from ..core.openrouter_gpt_image import WuddOpenRouterGPTImage
from ..core.openrouter_gpt_text import WuddOpenRouterGPTText
from ..core.audio_extract import WuddVideoAudioExtractor
from ..core.audio_replace import WuddReplaceVideoAudio
from ..core.group import WuddGroupSwitch
from ..core.image_alpha import WuddDropAlpha
from ..core.image_edge_pad import WuddEdgePad
from ..core.image_expand import WuddImageExpand
from ..core.image_list_importer import WuddImageListImporter
from ..core.image_save import WuddMultiSaveImage
from ..core.image_stitch import WuddImageStitch
from ..core.path_joiner import WuddPathJoiner
from ..core.text_multi_splitter import WuddMultiTextSplitter
from ..core.text_prompt_list import WuddPromptListFromText
from ..core.text_splitter import WuddTextSplitter
from ..core.video_concat import WuddConcatVideos
from ..core.video_fast_forward import WuddFastForwardVideo
from ..core.video_save import WuddSaveVideo
from ..core.browser import (
    BROWSER_CONNECTION_MODES,
    DEFAULT_CDP_URL,
    SUBMIT_ACTIONS,
    WuddChatGPTBrowser,
)


WUDD_V3_CATEGORY = "Wudd Nodes V3"
OPENROUTER_TEXT_CATEGORY = f"{WUDD_V3_CATEGORY}/OpenRouter/Text"
OPENROUTER_IMAGE_CATEGORY = f"{WUDD_V3_CATEGORY}/OpenRouter/Image"
CHATGPT_BROWSER_CATEGORY = f"{WUDD_V3_CATEGORY}/Browser"

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


class _OpenRouterV3Node(_FingerprintBackendNode):
    @classmethod
    def _api_image_kwargs(cls, images: IO.Autogrow.Type | None) -> dict[str, Any]:
        return _numbered_kwargs(images, "image_")


__all__ = [name for name in globals() if not name.startswith("__")]

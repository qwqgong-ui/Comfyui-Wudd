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
from ..core.text_save import WuddSaveText
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
IMAGE_CATEGORY = f"{WUDD_V3_CATEGORY}/Image"
VIDEO_CATEGORY = f"{WUDD_V3_CATEGORY}/Video"
TEXT_CATEGORY = f"{WUDD_V3_CATEGORY}/Text"
IO_CATEGORY = f"{WUDD_V3_CATEGORY}/IO"
CONTROL_CATEGORY = f"{WUDD_V3_CATEGORY}/Control"
OPENROUTER_TEXT_CATEGORY = f"{WUDD_V3_CATEGORY}/AI/OpenRouter/Text"
OPENROUTER_IMAGE_CATEGORY = f"{WUDD_V3_CATEGORY}/AI/OpenRouter/Image"
CHATGPT_BROWSER_CATEGORY = f"{WUDD_V3_CATEGORY}/AI/Browser"

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


_API_RUNTIME_INPUT_HELP = {
    "base_url": "OpenRouter-compatible API base URL.",
    "timeout_seconds": "Maximum time to wait for one API request before failing.",
    "verify_ssl": "Verify HTTPS certificates for API requests.",
}

_SYSTEM_INPUT_HELP = {
    "system_prompt": "Optional system message sent before the user prompt.",
    "extra_body_json": "Optional JSON object merged into the API request body.",
}

_OPENROUTER_TEXT_OUTPUT_HELP = {
    "text": "Primary model response text.",
    "reasoning": "Reasoning text returned by the provider when requested and available.",
    "response_id": "Provider response identifier, when returned by the API.",
}

_OPENROUTER_IMAGE_OUTPUT_HELP = {
    "image": "Generated image batch. A placeholder may be returned if the provider sends no image.",
    "text": "Text returned alongside the image response.",
    "response_id": "Provider response identifier, when returned by the API.",
}

_REFERENCE_IMAGE_INPUT_HELP = {
    "images": "Optional reference images sent with the prompt.",
    **{
        name: "Optional reference image sent with the prompt."
        for name in IMAGE_16_NAMES[:MAX_TEXT_IMAGE_INPUTS]
    },
}

_IMAGE_NODE_REFERENCE_INPUT_HELP = {
    "images": "Optional reference images for image generation or editing.",
    **{
        name: "Optional reference image for image generation or editing."
        for name in IMAGE_16_NAMES[:MAX_IMAGE_NODE_INPUTS]
    },
}

WUDD_V3_HELP: dict[str, dict[str, Any]] = {
    "WuddV3MultiSaveImage": {
        "description": "Save one or more IMAGE inputs to the ComfyUI output folder as PNG or Jpegli JPEG.",
        "inputs": {
            "images": "Dynamic IMAGE inputs. Add one slot for each image you want to save.",
            "filename_prefix": "Output path and filename prefix relative to the ComfyUI output folder.",
            "save_mode": "Choose whether to append numeric suffixes or overwrite matching files.",
            "extension": "Output image format.",
            "quality": "JPEG quality used by Jpegli mode.",
            "progressive": "Write progressive JPEG output when supported.",
            "enable_xyb": "Enable Jpegli XYB color transform for higher compression.",
            "chroma_subsampling": "JPEG chroma subsampling mode used by Jpegli.",
        },
    },
    "WuddV3SaveVideo": {
        "description": "Save one or more VIDEO inputs to the ComfyUI output folder with ffmpeg encoding.",
        "inputs": {
            "videos": "Dynamic VIDEO inputs. Add one slot for each video you want to save.",
            "filename_prefix": "Output path and filename prefix relative to the ComfyUI output folder.",
            "save_mode": "Choose whether to append numeric suffixes or overwrite matching files.",
            "codec": "Video codec used for the saved file.",
            "encoder": "ffmpeg encoder family. Hardware options require matching hardware and ffmpeg support.",
            "container": "Output container format.",
            "crf": "Constant rate factor. Lower values usually produce higher quality and larger files.",
            "preset": "Encoder speed and compression preset.",
            "audio_mode": "Copy audio, re-encode audio to AAC, or remove audio.",
        },
    },
    "WuddV3FastForwardVideo": {
        "description": "Speed up a VIDEO by multiplier or by targeting a final duration.",
        "inputs": {
            "video": "Input VIDEO to speed up.",
            "mode": "Choose direct speed multiplier or target final duration.",
            "speed_multiplier": "Playback speed multiplier, for example 2.0 for double speed.",
            "target_seconds": "Desired output duration in seconds. Speed is calculated from source duration.",
            "audio_mode": "Keep tempo-adjusted audio or remove audio.",
        },
        "outputs": {"video": "Speed-adjusted VIDEO output."},
    },
    "WuddV3ConcatVideos": {
        "description": "Concatenate multiple VIDEO inputs in slot order and return one VIDEO.",
        "inputs": {
            "videos": "Dynamic VIDEO inputs. Videos are concatenated in slot order.",
            "resize_mode": "How each segment is adapted to the first video's size.",
            "audio_mode": "Keep and normalize audio, or remove audio from the result.",
        },
        "outputs": {"video": "Concatenated VIDEO output."},
    },
    "WuddV3TextSplitter": {
        "description": "Split multiline text and return one selected line.",
        "inputs": {
            "text": "Multiline text to split.",
            "index": "Zero-based line index to return after optional filtering.",
            "skip_empty": "Ignore blank lines before selecting the indexed line.",
        },
        "outputs": {"text": "Selected line, or an empty string when the index is out of range."},
    },
    "WuddV3MultiTextSplitter": {
        "description": "Split multiline text into up to 16 STRING outputs.",
        "inputs": {
            "text": "Multiline text to split.",
            "count": "Number of output slots intended for use.",
            "skip_empty": "Ignore blank lines before assigning output slots.",
        },
        "outputs": {
            name: "Split line output. Missing lines return an empty string."
            for name in [f"line_{i}" for i in range(WuddMultiTextSplitter.MAX_OUTPUTS)]
        },
    },
    "WuddV3PromptListFromText": {
        "description": "Parse multiline text into a prompt list and count.",
        "inputs": {
            "text": "Text containing one or more prompts.",
            "skip_empty": "Ignore blank lines while building the prompt list.",
            "strip_numbering": "Remove common leading numbering such as '1.' or 'page 2:'.",
        },
        "outputs": {
            "prompts": "List of parsed prompt strings.",
            "count": "Number of prompts in the list.",
        },
    },
    "WuddV3SaveText": {
        "description": "Save STRING text to a UTF-8 file under output, input, or temp.",
        "inputs": {
            "text": "Text content to write.",
            "root_dir": "ComfyUI root folder used as the save base.",
            "file": "Relative file path below the selected root folder.",
            "append": "Write mode: overwrite, append, or create only when missing.",
            "insert": "When appending, insert new text at the beginning instead of the end.",
        },
        "outputs": {"path": "Absolute path to the saved text file."},
    },
    "WuddV3DropAlpha": {
        "description": "Composite transparent image areas over a generated background and return RGB IMAGE.",
        "inputs": {
            "image": "Input IMAGE that may contain alpha.",
            "mode": "Background fill mode for transparent areas.",
            "tile_size": "Checkerboard tile size in pixels.",
            "fill_color": "Solid background color in hex format.",
            "auto_crop": "Crop to non-transparent content after compositing.",
            "padding": "Extra pixels to keep around the auto-cropped content.",
            "mask": "Optional MASK where 1 marks transparent area to replace.",
        },
        "outputs": {"image": "RGB IMAGE with alpha removed."},
    },
    "WuddV3ImageExpand": {
        "description": "Expand an image by whole-image blocks in one direction.",
        "inputs": {
            "image": "Input IMAGE to expand.",
            "direction": "Side where new area is added.",
            "count": "Number of whole-image blocks to add.",
            "mode": "Fill mode for the new area.",
            "tile_size": "Checkerboard tile size in pixels.",
            "fill_color": "Solid fill color in hex format.",
        },
        "outputs": {
            "image": "Expanded IMAGE output.",
            "width": "Expanded image width in pixels.",
            "height": "Expanded image height in pixels.",
        },
    },
    "WuddV3EdgePad": {
        "description": "Extend vertical image edges and blend neighboring images for long-image preprocessing.",
        "inputs": {
            "images": "Dynamic IMAGE inputs processed in slot order.",
            "pad_px": "Number of pixels added to the top and bottom edges.",
            "blend_pct": "Height percentage used as the transition band between pad and original image.",
            "pad_sigma": "Gaussian blur strength for cross-image edge padding.",
            "blend_sigma": "Gaussian blur strength for the original-to-padding transition.",
            "chamfer_pct": "Percentage depth of the edge chamfer. Use 0 to disable.",
        },
        "outputs": {
            name: "Padded IMAGE output for the matching input slot."
            for name in IMAGE_16_NAMES
        },
    },
    "WuddV3ImageListImporter": {
        "description": "Import multiple images from ComfyUI input files or from a folder.",
        "inputs": {
            "mode": "Choose individual file selection or folder scan mode.",
            "image_count": "Number of image outputs to load.",
            "folder_path": "Folder path, absolute or relative to the ComfyUI input folder.",
            **{
                name: "Image file selected from the ComfyUI input folder."
                for name in IMAGE_50_NAMES
            },
        },
        "outputs": {
            name: "Imported IMAGE output for the matching slot."
            for name in IMAGE_50_NAMES
        },
    },
    "WuddV3ImageStitch": {
        "description": "Stitch multiple images linearly in one direction.",
        "inputs": {
            "images": "Dynamic IMAGE inputs stitched in slot order.",
            "direction": "Direction to place later images relative to earlier ones.",
            "gap": "Pixel gap inserted between images.",
        },
        "outputs": {"image": "Stitched IMAGE output."},
    },
    "WuddV3PathJoiner": {
        "description": "Join up to five path segments with forward slashes.",
        "inputs": {
            "count": "Number of path segments to include.",
            **{
                f"segment_{i}": f"Path segment {i}. Blank segments are ignored."
                for i in range(1, 6)
            },
        },
        "outputs": {"path": "Joined path string using '/' separators."},
    },
    "WuddV3VideoAudioExtractor": {
        "description": "Extract AUDIO, sample rate, and duration from a VIDEO input.",
        "inputs": {
            "video": "Input VIDEO containing an audio stream.",
            "audio_stream_index": "Zero-based audio stream index to extract.",
        },
        "outputs": {
            "audio": "Extracted AUDIO object.",
            "sample_rate": "Audio sample rate in Hz.",
            "duration_seconds": "Extracted audio duration in seconds.",
        },
    },
    "WuddV3ReplaceVideoAudio": {
        "description": "Replace a VIDEO input's audio track with a supplied AUDIO input.",
        "inputs": {
            "video": "Input VIDEO whose audio track will be replaced.",
            "audio": "Replacement AUDIO input.",
            "output_format": "Container format for the temporary output video.",
            "audio_bitrate": "AAC bitrate used for the replacement audio.",
            "end_mode": "How to handle duration mismatch between video and audio.",
        },
        "outputs": {"video": "VIDEO with the replacement audio track."},
    },
    "WuddV3OpenRouterGPTText": {
        "description": "Call an OpenRouter GPT text or multimodal model and return text, reasoning, and response id.",
        "inputs": {
            "prompt": "User prompt sent to the model.",
            "api_key": "OpenRouter API key.",
            "model": "OpenRouter model identifier.",
            "max_tokens": "Maximum number of output tokens requested.",
            "reasoning_effort": "Requested reasoning effort, when supported by the model.",
            "include_reasoning": "Ask the provider to include reasoning content when supported.",
            "response_format": "Text or JSON-style response format hint.",
            "seed": "Deterministic seed when supported. Changes after generation if ComfyUI control is enabled.",
            **_API_RUNTIME_INPUT_HELP,
            **_SYSTEM_INPUT_HELP,
            **_REFERENCE_IMAGE_INPUT_HELP,
        },
        "outputs": _OPENROUTER_TEXT_OUTPUT_HELP,
    },
    "WuddV3OpenRouterClaudeText": {
        "description": "Call an OpenRouter Claude text model and return text, reasoning, and response id.",
        "inputs": {
            "prompt": "User prompt sent to the model.",
            "api_key": "OpenRouter API key.",
            "model": "OpenRouter model identifier.",
            "max_tokens": "Maximum number of output tokens requested.",
            "temperature": "Sampling temperature.",
            "top_p": "Nucleus sampling value.",
            "top_k": "Top-k sampling value. Use 0 for provider default.",
            "verbosity": "Provider-specific verbosity hint.",
            "reasoning_effort": "Requested reasoning effort, when supported by the model.",
            "include_reasoning": "Ask the provider to include reasoning content when supported.",
            "stop_sequences": "Optional stop sequences, one per line.",
            **_API_RUNTIME_INPUT_HELP,
            **_SYSTEM_INPUT_HELP,
        },
        "outputs": _OPENROUTER_TEXT_OUTPUT_HELP,
    },
    "WuddV3OpenRouterGeminiText": {
        "description": "Call an OpenRouter Gemini text or multimodal model and return text, reasoning, and response id.",
        "inputs": {
            "prompt": "User prompt sent to the model.",
            "api_key": "OpenRouter API key.",
            "model": "OpenRouter model identifier.",
            "max_tokens": "Maximum number of output tokens requested.",
            "temperature": "Sampling temperature.",
            "top_p": "Nucleus sampling value.",
            "reasoning_effort": "Requested reasoning effort, when supported by the model.",
            "include_reasoning": "Ask the provider to include reasoning content when supported.",
            "response_format": "Text or JSON-style response format hint.",
            "seed": "Deterministic seed when supported. Changes after generation if ComfyUI control is enabled.",
            "stop_sequences": "Optional stop sequences, one per line.",
            **_API_RUNTIME_INPUT_HELP,
            **_SYSTEM_INPUT_HELP,
            **_REFERENCE_IMAGE_INPUT_HELP,
        },
        "outputs": _OPENROUTER_TEXT_OUTPUT_HELP,
    },
    "WuddV3OpenRouterGPTImage": {
        "description": "Call an OpenRouter GPT image model and return generated image, text, and response id.",
        "inputs": {
            "prompt": "Image generation or editing prompt.",
            "api_key": "OpenRouter API key.",
            "model": "OpenRouter model identifier.",
            "response_modalities": "Response modalities requested from the model.",
            "aspect_ratio": "Requested output aspect ratio.",
            "image_size": "Requested provider image size.",
            "max_tokens": "Maximum number of output tokens requested for accompanying text.",
            "reasoning_effort": "Requested reasoning effort, when supported by the model.",
            "seed": "Deterministic seed when supported. Changes after generation if ComfyUI control is enabled.",
            **_API_RUNTIME_INPUT_HELP,
            **_SYSTEM_INPUT_HELP,
            **_IMAGE_NODE_REFERENCE_INPUT_HELP,
        },
        "outputs": _OPENROUTER_IMAGE_OUTPUT_HELP,
    },
    "WuddV3OpenRouterGeminiImage": {
        "description": "Call an OpenRouter Gemini image model and return generated image, text, and response id.",
        "inputs": {
            "prompt": "Image generation or editing prompt.",
            "api_key": "OpenRouter API key.",
            "model": "OpenRouter model identifier.",
            "response_modalities": "Response modalities requested from the model.",
            "aspect_ratio": "Requested output aspect ratio.",
            "image_size": "Requested provider image size.",
            "max_tokens": "Maximum number of output tokens requested for accompanying text.",
            "temperature": "Sampling temperature.",
            "top_p": "Nucleus sampling value.",
            "reasoning_effort": "Requested reasoning effort, when supported by the model.",
            "seed": "Deterministic seed when supported. Changes after generation if ComfyUI control is enabled.",
            **_API_RUNTIME_INPUT_HELP,
            **_SYSTEM_INPUT_HELP,
            **_IMAGE_NODE_REFERENCE_INPUT_HELP,
        },
        "outputs": _OPENROUTER_IMAGE_OUTPUT_HELP,
    },
    "WuddV3GroupSwitch": {
        "description": "Enable, mute, or bypass nodes inside ComfyUI canvas groups from one switch node.",
        "inputs": {
            "enabled": "Master on/off state for the selected group or all listed groups.",
            "group_name": "Target group title. Leave blank for all groups, or use self/current/auto for the containing group.",
            "off_mode": "Use mute for Never mode or bypass for Bypass mode when disabled.",
        },
        "outputs": {
            "enabled": "Current enabled state.",
            "group_name": "Configured target group name.",
        },
    },
    "WuddV3ChatGPTBrowser": {
        "description": "Submit a prompt and optional images to ChatGPT through a local Chrome or Edge browser.",
        "inputs": {
            "prompt": "Prompt text to submit to ChatGPT.",
            "connection_mode": "How to connect to or launch Chrome/Edge.",
            "cdp_url": "Chrome DevTools Protocol URL used by connect_cdp mode.",
            "wait_timeout_seconds": "Maximum time to wait for ChatGPT to finish responding.",
            "stable_seconds": "How long the response must remain unchanged before it is considered complete.",
            "upload_wait_seconds": "Extra wait time after image upload before submitting.",
            "new_chat": "Start a new ChatGPT conversation before submitting.",
            "submit_action": "Submit by pressing Enter or clicking the send button.",
            "keep_browser_open": "Keep a browser launched by the node open after execution.",
            "background_browser": "Launch the browser with background-friendly options when possible.",
            "parallel_pages": "Maximum browser pages used by concurrent executions.",
            "run_id": "Manual cache-busting id. Change it to force a rerun.",
            "images": "Optional reference images uploaded before submitting the prompt.",
            "browser_executable": "Optional explicit Chrome or Edge executable path.",
            "close_page_after_run": "Close the ChatGPT tab after the node finishes.",
            "image_error_retries": "Retry count when ChatGPT reports image generation failure without images.",
        },
        "outputs": {
            "text": "Latest assistant response text.",
            "conversation_url": "URL of the ChatGPT conversation after submission.",
            "images": "Images from the latest assistant response, or a placeholder when none are found.",
            "image_count": "Number of real response images found.",
        },
    },
}


def _with_help(schema: IO.Schema) -> IO.Schema:
    help_data = WUDD_V3_HELP.get(schema.node_id)
    if not help_data:
        return schema

    schema.description = help_data.get("description", schema.description)
    input_help = help_data.get("inputs", {})
    output_help = help_data.get("outputs", {})

    for input_item in schema.inputs or []:
        try:
            candidates = input_item.get_all()
        except Exception:
            candidates = [input_item]
        for candidate in candidates:
            tooltip = input_help.get(getattr(candidate, "id", None))
            if tooltip:
                candidate.tooltip = tooltip

    for output_item in schema.outputs or []:
        tooltip = output_help.get(getattr(output_item, "id", None))
        if tooltip:
            output_item.tooltip = tooltip

    return schema


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

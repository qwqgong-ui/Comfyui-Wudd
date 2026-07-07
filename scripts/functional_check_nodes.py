from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
COMFY_ROOT = REPO_ROOT.parent.parent
PACKAGE_ALIAS = "wudd_v3_functional_check"

sys.path.insert(0, str(COMFY_ROOT))

import folder_paths  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from comfy_api.latest import IO, InputImpl  # noqa: E402


class EnvUnavailable(RuntimeError):
    pass


@dataclass
class Case:
    node_id: str
    label: str
    run: Callable[[type, "CheckContext"], Awaitable[dict[str, Any]]]


@dataclass
class CheckContext:
    package: Any
    temp_dir: Path
    input_dir: Path
    output_dir: Path
    sample_image_rgb: torch.Tensor
    sample_image_alt: torch.Tensor
    sample_mask: torch.Tensor
    sample_audio: dict[str, Any]
    sample_video_path: Path
    sample_video_alt_path: Path
    sample_input_image_name: str
    sample_input_folder: Path
    ffmpeg: str


def load_package() -> Any:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_ALIAS,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load package from {REPO_ROOT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def hidden_holder() -> SimpleNamespace:
    return SimpleNamespace(
        prompt={"functional_check": True},
        extra_pnginfo={"functional_check": {"created_at": int(time.time())}},
        unique_id="wudd_v3_functional_check",
    )


def prepare_node_class(node_cls: type) -> type:
    node_cls.GET_SCHEMA()
    node_cls.hidden = hidden_holder()
    return node_cls


def node_result(value: Any) -> tuple[tuple[Any, ...], Any]:
    if isinstance(value, IO.NodeOutput):
        return tuple(value.result or ()), value.ui
    if isinstance(value, tuple):
        return value, None
    if isinstance(value, dict):
        output = IO.NodeOutput.from_dict(value)
        return tuple(output.result or ()), output.ui
    if value is None:
        return (), None
    return (value,), None


def summarize_value(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        result = {
            "type": "tensor",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
        if value.numel():
            result["min"] = round(float(value.min().item()), 6)
            result["max"] = round(float(value.max().item()), 6)
        return result
    if isinstance(value, dict):
        if "waveform" in value and "sample_rate" in value:
            waveform = value["waveform"]
            return {
                "type": "audio",
                "sample_rate": int(value["sample_rate"]),
                "waveform": summarize_value(waveform),
            }
        return {str(k): summarize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        summary: dict[str, Any] = {"type": type(value).__name__, "len": len(items)}
        if len(items) <= 6:
            summary["items"] = [summarize_value(item) for item in items]
        else:
            summary["head"] = [summarize_value(item) for item in items[:3]]
            summary["tail"] = [summarize_value(item) for item in items[-2:]]
        return summary
    if hasattr(value, "get_stream_source"):
        info: dict[str, Any] = {"type": type(value).__name__}
        try:
            source = value.get_stream_source()
            if isinstance(source, (str, os.PathLike)):
                path = Path(source)
                info.update(
                    {
                        "source": str(path),
                        "exists": path.exists(),
                        "size": path.stat().st_size if path.exists() else None,
                    }
                )
            else:
                info["source"] = type(source).__name__
        except Exception as exc:
            info["source_error"] = f"{type(exc).__name__}: {exc}"
        try:
            width, height = value.get_dimensions()
            info["dimensions"] = [int(width), int(height)]
        except Exception:
            pass
        try:
            info["frame_rate"] = str(value.get_frame_rate())
        except Exception:
            pass
        return info
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value):
            return round(value, 6)
        return str(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return {"type": type(value).__name__, "repr": repr(value)[:200]}


def summarize_output(value: Any) -> dict[str, Any]:
    result, ui = node_result(value)
    return {"result": summarize_value(result), "ui": summarize_value(ui)}


def assert_tensor_shape(value: Any, dims: int | None = None) -> torch.Tensor:
    if not isinstance(value, torch.Tensor):
        raise AssertionError(f"Expected tensor output, got {type(value).__name__}")
    if dims is not None and value.ndim != dims:
        raise AssertionError(f"Expected {dims}D tensor, got shape {tuple(value.shape)}")
    return value


def assert_video_exists(value: Any) -> None:
    if not hasattr(value, "get_stream_source"):
        raise AssertionError(f"Expected VIDEO output, got {type(value).__name__}")
    source = value.get_stream_source()
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        if not path.exists() or path.stat().st_size <= 0:
            raise AssertionError(f"VIDEO source does not exist or is empty: {path}")


def image_tensor(width: int, height: int, offset: float = 0.0) -> torch.Tensor:
    y = torch.linspace(0.0, 1.0, height).view(height, 1, 1)
    x = torch.linspace(0.0, 1.0, width).view(1, width, 1)
    r = (x + offset).remainder(1.0).expand(height, width, 1)
    g = (y + offset / 2.0).remainder(1.0).expand(height, width, 1)
    b = torch.full((height, width, 1), 0.35 + offset / 4.0)
    return torch.cat([r, g, b], dim=-1).unsqueeze(0).float()


def mask_tensor(width: int, height: int) -> torch.Tensor:
    mask = torch.zeros((1, height, width), dtype=torch.float32)
    mask[:, :, width // 2 :] = 1.0
    return mask


def audio_dict(sample_rate: int = 16000, seconds: float = 0.75) -> dict[str, Any]:
    samples = max(1, int(sample_rate * seconds))
    t = torch.arange(samples, dtype=torch.float32) / float(sample_rate)
    wave = 0.25 * torch.sin(2.0 * math.pi * 440.0 * t)
    stereo = torch.stack([wave, wave], dim=0).unsqueeze(0)
    return {"waveform": stereo, "sample_rate": sample_rate}


def save_input_image(path: Path, tensor: torch.Tensor) -> None:
    arr = (tensor[0].detach().cpu().numpy() * 255.0).clip(0, 255).astype("uint8")
    Image.fromarray(arr, mode="RGB").save(path)


def run_subprocess(cmd: list[str], description: str) -> None:
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"{description} failed: {stderr or exc}") from exc


def ffmpeg_encoders(ffmpeg: str) -> str:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    return result.stdout


def choose_save_video_codec(ffmpeg: str) -> tuple[str, str]:
    encoders = ffmpeg_encoders(ffmpeg)
    if "libx265" in encoders:
        return "h265", "cpu"
    if "libsvtav1" in encoders or "libaom-av1" in encoders:
        return "av1", "cpu"
    return "h265", "cpu"


def create_sample_video(ffmpeg: str, path: Path, freq: int, width: int = 64, height: int = 48) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate=12",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:sample_rate=16000",
        "-t",
        "0.75",
        "-shortest",
        "-pix_fmt",
        "yuv420p",
    ]
    attempts = [
        base + ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)],
        base + ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "aac", str(path)],
    ]
    last_error: Exception | None = None
    for index, cmd in enumerate(attempts, start=1):
        try:
            run_subprocess(cmd, f"create sample video attempt {index}")
            if path.exists() and path.stat().st_size > 0:
                return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not create sample video: {last_error}")


def prepare_context(package: Any) -> CheckContext:
    from wudd_v3_functional_check.core.ffmpeg import resolve_ffmpeg_exe

    temp_dir = Path(folder_paths.get_temp_directory()) / "wudd_node_functional_check"
    input_dir = Path(folder_paths.get_input_directory())
    output_dir = Path(folder_paths.get_output_directory())
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    sample_image_rgb = image_tensor(16, 16, 0.1)
    sample_image_alt = image_tensor(8, 16, 0.4)
    sample_mask = mask_tensor(16, 16)
    sample_audio = audio_dict()

    input_image_path = input_dir / "wudd_node_functional_check.png"
    save_input_image(input_image_path, sample_image_rgb)

    input_folder = input_dir / "wudd_node_functional_check_folder"
    input_folder.mkdir(parents=True, exist_ok=True)
    save_input_image(input_folder / "sample.00001.01.png", image_tensor(12, 10, 0.2))
    save_input_image(input_folder / "sample.00001.02.png", image_tensor(14, 10, 0.5))

    ffmpeg = resolve_ffmpeg_exe()
    sample_video_path = temp_dir / "sample_a.mp4"
    sample_video_alt_path = temp_dir / "sample_b.mp4"
    create_sample_video(ffmpeg, sample_video_path, 440)
    create_sample_video(ffmpeg, sample_video_alt_path, 660)

    return CheckContext(
        package=package,
        temp_dir=temp_dir,
        input_dir=input_dir,
        output_dir=output_dir,
        sample_image_rgb=sample_image_rgb,
        sample_image_alt=sample_image_alt,
        sample_mask=sample_mask,
        sample_audio=sample_audio,
        sample_video_path=sample_video_path,
        sample_video_alt_path=sample_video_alt_path,
        sample_input_image_name=input_image_path.name,
        sample_input_folder=input_folder,
        ffmpeg=ffmpeg,
    )


def video_from(path: Path) -> Any:
    return InputImpl.VideoFromFile(str(path))


async def case_text_splitter(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {"text": "zero\n\none\ntwo", "index": 1, "skip_empty": True}
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    if result[0] != "one":
        raise AssertionError(f"Expected 'one', got {result[0]!r}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_multi_text_splitter(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {"text": "9:16.vertical prompt\n\nb\nc", "count": 3, "skip_empty": True}
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    if result[:3] != ("9:16.vertical prompt", "b", "c") or len(result) != 16:
        raise AssertionError(f"Unexpected split result: {result!r}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_prompt_list(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "text": "1. first\n\npage 2: second\n提示词\n```text\nthird\n```\n9:16.vertical prompt",
        "skip_empty": True,
        "strip_numbering": True,
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    if result[0] != ["first", "second", "third", "9:16.vertical prompt"] or result[1] != 4:
        raise AssertionError(f"Unexpected prompt list result: {result!r}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_path_joiner(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "count": 4,
        "segment_1": "root",
        "segment_2": "",
        "segment_3": "child",
        "segment_4": "leaf",
        "segment_5": "ignored",
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    if result[0] != "root/child/leaf":
        raise AssertionError(f"Unexpected joined path: {result[0]!r}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_save_text(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    text = "functional save text\nsecond line"
    inputs = {
        "text": text,
        "root_dir": "temp",
        "file": "wudd_node_functional_check/saved_text.txt",
        "append": "overwrite",
        "insert": False,
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    saved = Path(result[0])
    if saved != ctx.temp_dir / "saved_text.txt":
        raise AssertionError(f"Unexpected saved path: {saved}")
    if not saved.exists() or saved.read_text(encoding="utf-8") != text:
        raise AssertionError(f"Saved text not found or content mismatch: {saved}")
    return {"inputs": inputs, "saved_file": str(saved), "output": summarize_output(output)}


async def case_group_switch(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {"enabled": False, "group_name": "groupA", "off_mode": "mute"}
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    if result != (False, "groupA"):
        raise AssertionError(f"Unexpected group switch output: {result!r}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_drop_alpha(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "image": ctx.sample_image_rgb,
        "mode": {"mode": "fill_color", "fill_color": "#ff0000"},
        "auto_crop": False,
        "padding": 0,
        "mask": ctx.sample_mask,
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    tensor = assert_tensor_shape(result[0], 4)
    if list(tensor.shape) != [1, 16, 16, 3]:
        raise AssertionError(f"Unexpected image shape: {tuple(tensor.shape)}")
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_image_expand(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "image": ctx.sample_image_rgb,
        "direction": "right",
        "count": 1,
        "mode": {"mode": "checkerboard", "tile_size": 4},
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    tensor = assert_tensor_shape(result[0], 4)
    if list(tensor.shape) != [1, 16, 32, 3] or result[1:] != (32, 16):
        raise AssertionError(f"Unexpected expand output: {summarize_value(result)}")
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_image_stitch(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "images": {"image_1": ctx.sample_image_rgb, "image_2": ctx.sample_image_alt},
        "direction": "right",
        "gap": 2,
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    tensor = assert_tensor_shape(result[0], 4)
    if tensor.shape[1] != 16 or tensor.shape[2] <= 16:
        raise AssertionError(f"Unexpected stitch shape: {tuple(tensor.shape)}")
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_edge_pad(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "images": {"image_1": ctx.sample_image_rgb, "image_2": ctx.sample_image_rgb.clone()},
        "pad_px": 10,
        "blend_pct": 3.0,
        "pad_sigma": 2.0,
        "blend_sigma": 1.0,
        "chamfer_pct": 5.0,
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    if len(result) != 16:
        raise AssertionError(f"Expected 16 outputs, got {len(result)}")
    first = assert_tensor_shape(result[0], 4)
    second = assert_tensor_shape(result[1], 4)
    if first.shape[1] != 36 or second.shape[1] != 36:
        raise AssertionError(f"Unexpected edge pad shapes: {first.shape}, {second.shape}")
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_image_list_files(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "mode": {
            "mode": "files",
            "image_count": 1,
            "image_1": ctx.sample_input_image_name,
        }
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    tensor = assert_tensor_shape(result[0], 4)
    if tensor.shape[1] != 16 or tensor.shape[2] != 16:
        raise AssertionError(f"Unexpected imported file shape: {tuple(tensor.shape)}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_image_list_folder(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "mode": {
            "mode": "folder",
            "image_count": 2,
            "folder_path": str(ctx.sample_input_folder),
        }
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    first = assert_tensor_shape(result[0], 4)
    second = assert_tensor_shape(result[1], 4)
    if first.shape[1] != 10 or second.shape[1] != 10:
        raise AssertionError(f"Unexpected imported folder shapes: {first.shape}, {second.shape}")
    return {"inputs": inputs, "output": summarize_output(output)}


async def case_multi_save_image(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "images": {"image_1": ctx.sample_image_rgb},
        "filename_prefix": "wudd_node_check/functional_image",
        "save_mode": "overwrite",
        "extension": {"extension": "png"},
    }
    output = await node_cls.execute(**inputs)
    result, ui = node_result(output)
    images = (ui or {}).get("images", [])
    if result != ():
        raise AssertionError(f"Save image should not return result values: {result!r}")
    if not images:
        raise AssertionError("Save image UI did not include image entries")
    saved = ctx.output_dir / images[0].get("subfolder", "") / images[0]["filename"]
    if not saved.exists() or saved.stat().st_size <= 0:
        raise AssertionError(f"Saved image not found: {saved}")
    return {"inputs": summarize_value(inputs), "saved_file": str(saved), "output": summarize_output(output)}


async def case_video_audio_extractor(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {"video": video_from(ctx.sample_video_path), "audio_stream_index": 0}
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    audio = result[0]
    if not isinstance(audio, dict) or "waveform" not in audio or result[1] <= 0 or result[2] <= 0:
        raise AssertionError(f"Unexpected audio extract result: {summarize_value(result)}")
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_replace_video_audio(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "video": video_from(ctx.sample_video_path),
        "audio": ctx.sample_audio,
        "output_format": "mp4",
        "audio_bitrate": "128k",
        "end_mode": "keep_video_length",
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    assert_video_exists(result[0])
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_fast_forward_video(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "video": video_from(ctx.sample_video_path),
        "mode": {"mode": "speed_multiplier", "speed_multiplier": 2.0},
        "audio_mode": "none",
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    assert_video_exists(result[0])
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_concat_videos(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    inputs = {
        "videos": {
            "video_1": video_from(ctx.sample_video_path),
            "video_2": video_from(ctx.sample_video_alt_path),
        },
        "resize_mode": "fit_to_first",
        "audio_mode": "none",
    }
    output = await node_cls.execute(**inputs)
    result, _ = node_result(output)
    assert_video_exists(result[0])
    return {"inputs": summarize_value(inputs), "output": summarize_output(output)}


async def case_save_video(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    codec, encoder = choose_save_video_codec(ctx.ffmpeg)
    inputs = {
        "videos": {"video_1": video_from(ctx.sample_video_path)},
        "filename_prefix": "wudd_node_check/functional_video",
        "save_mode": "overwrite",
        "codec": codec,
        "encoder": encoder,
        "container": "mp4",
        "crf": 32,
        "preset": "fast",
        "audio_mode": "none",
    }
    output = await node_cls.execute(**inputs)
    _, ui = node_result(output)
    images = (ui or {}).get("images", [])
    if not images:
        raise AssertionError("Save video UI did not include video entries")
    saved = ctx.output_dir / images[0].get("subfolder", "") / images[0]["filename"]
    if not saved.exists() or saved.stat().st_size <= 0:
        raise AssertionError(f"Saved video not found: {saved}")
    return {"inputs": summarize_value(inputs), "saved_file": str(saved), "output": summarize_output(output)}


async def case_chatgpt_browser(node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    from wudd_v3_functional_check.core.browser import DEFAULT_CDP_URL, _is_cdp_ready

    cdp_url = DEFAULT_CDP_URL
    try:
        from playwright.async_api import async_playwright as _async_playwright  # noqa: F401
    except ImportError as exc:
        raise EnvUnavailable(f"Playwright is not installed: {exc}") from exc

    if not _is_cdp_ready(cdp_url):
        raise EnvUnavailable(
            f"CDP endpoint is not available at {cdp_url}. "
            "Start Chrome/Edge with --remote-debugging-port=9222 to run the live ChatGPT flow."
        )

    inputs = {
        "prompt": "Reply with OK only.",
        "connection_mode": "connect_cdp",
        "cdp_url": cdp_url,
        "wait_timeout_seconds": 10,
        "stable_seconds": 0.5,
        "upload_wait_seconds": 0.0,
        "new_chat": True,
        "submit_action": "press_enter",
        "keep_browser_open": True,
        "close_page_after_run": True,
        "background_browser": True,
        "parallel_pages": 1,
        "run_id": int(time.time()),
        "images": None,
        "browser_executable": "",
    }
    output = await asyncio.wait_for(node_cls.execute(**inputs), timeout=30.0)
    result, _ = node_result(output)
    if len(result) != 4 or not isinstance(result[0], str) or not isinstance(result[1], str):
        raise AssertionError(f"Unexpected browser output: {summarize_value(result)}")
    return {"inputs": inputs, "output": summarize_output(output)}


CASES: list[Case] = [
    Case("WuddV3TextSplitter", "line selection", case_text_splitter),
    Case("WuddV3MultiTextSplitter", "multi output split", case_multi_text_splitter),
    Case("WuddV3PromptListFromText", "prompt list parsing", case_prompt_list),
    Case("WuddV3PathJoiner", "path join", case_path_joiner),
    Case("WuddV3SaveText", "save text", case_save_text),
    Case("WuddV3GroupSwitch", "switch output", case_group_switch),
    Case("WuddV3DropAlpha", "mask composite", case_drop_alpha),
    Case("WuddV3ImageExpand", "expand right", case_image_expand),
    Case("WuddV3ImageStitch", "stitch two images", case_image_stitch),
    Case("WuddV3EdgePad", "pad two images", case_edge_pad),
    Case("WuddV3ImageListImporter", "files mode", case_image_list_files),
    Case("WuddV3ImageListImporter", "folder mode", case_image_list_folder),
    Case("WuddV3MultiSaveImage", "save png", case_multi_save_image),
    Case("WuddV3VideoAudioExtractor", "extract audio", case_video_audio_extractor),
    Case("WuddV3ReplaceVideoAudio", "replace audio", case_replace_video_audio),
    Case("WuddV3FastForwardVideo", "speed multiplier", case_fast_forward_video),
    Case("WuddV3ConcatVideos", "concat two videos", case_concat_videos),
    Case("WuddV3SaveVideo", "save encoded video", case_save_video),
    Case("WuddV3ChatGPTBrowser", "connect_cdp live flow", case_chatgpt_browser),
]


def openrouter_node(node_id: str) -> bool:
    return "OpenRouter" in node_id


async def run_case(case: Case, node_cls: type, ctx: CheckContext) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        details = await case.run(node_cls, ctx)
        status = "PASS"
        error = None
    except EnvUnavailable as exc:
        details = {}
        status = "ENV_FAIL"
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        details = {"traceback": traceback.format_exc()}
        status = "FAIL"
        error = f"{type(exc).__name__}: {exc}"
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return {
        "node_id": case.node_id,
        "case": case.label,
        "status": status,
        "duration_ms": duration_ms,
        "error": error,
        "details": details,
    }


def print_table(results: list[dict[str, Any]]) -> None:
    widths = {
        "status": max(len("STATUS"), *(len(item["status"]) for item in results)),
        "node": max(len("NODE"), *(len(item["node_id"]) for item in results)),
        "case": max(len("CASE"), *(len(item["case"]) for item in results)),
    }
    print(f"{'STATUS':<{widths['status']}}  {'NODE':<{widths['node']}}  {'CASE':<{widths['case']}}  MS      ERROR")
    print("-" * (widths["status"] + widths["node"] + widths["case"] + 30))
    for item in results:
        error = item["error"] or ""
        print(
            f"{item['status']:<{widths['status']}}  "
            f"{item['node_id']:<{widths['node']}}  "
            f"{item['case']:<{widths['case']}}  "
            f"{item['duration_ms']:<7} {error}"
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Functional execution check for ComfyUI-Wudd-V3 nodes.")
    parser.add_argument("--strict-env", action="store_true", help="Treat ENV_FAIL as a failing exit code.")
    args = parser.parse_args()

    package = load_package()
    node_map: dict[str, type] = package.WUDD_V3_NODE_CLASSES
    skipped_openrouter = sorted(node_id for node_id in node_map if openrouter_node(node_id))

    ctx = prepare_context(package)
    results: list[dict[str, Any]] = []

    schema_errors: list[dict[str, Any]] = []
    for node_id, node_cls in sorted(node_map.items()):
        if openrouter_node(node_id):
            continue
        try:
            prepare_node_class(node_cls)
        except Exception as exc:
            schema_errors.append(
                {
                    "node_id": node_id,
                    "case": "schema",
                    "status": "FAIL",
                    "duration_ms": 0.0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "details": {"traceback": traceback.format_exc()},
                }
            )

    results.extend(schema_errors)
    for case in CASES:
        if case.node_id not in node_map:
            results.append(
                {
                    "node_id": case.node_id,
                    "case": case.label,
                    "status": "FAIL",
                    "duration_ms": 0.0,
                    "error": "Node is not registered.",
                    "details": {},
                }
            )
            continue
        node_cls = prepare_node_class(node_map[case.node_id])
        results.append(await run_case(case, node_cls, ctx))

    report = {
        "repo_root": str(REPO_ROOT),
        "comfy_root": str(COMFY_ROOT),
        "python": sys.executable,
        "ffmpeg": ctx.ffmpeg,
        "skipped_openrouter_nodes": skipped_openrouter,
        "summary": {
            "registered_nodes": len(node_map),
            "openrouter_skipped": len(skipped_openrouter),
            "cases": len(results),
            "pass": sum(1 for item in results if item["status"] == "PASS"),
            "fail": sum(1 for item in results if item["status"] == "FAIL"),
            "env_fail": sum(1 for item in results if item["status"] == "ENV_FAIL"),
        },
        "results": results,
    }
    report_path = ctx.temp_dir / "functional_check_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print_table(results)
    print()
    print(f"Report: {report_path}")
    print(f"Skipped OpenRouter nodes: {', '.join(skipped_openrouter) or 'none'}")
    print("Summary:", json.dumps(report["summary"], ensure_ascii=False))

    has_fail = any(item["status"] == "FAIL" for item in results)
    has_env_fail = any(item["status"] == "ENV_FAIL" for item in results)
    if has_fail or (args.strict_env and has_env_fail):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

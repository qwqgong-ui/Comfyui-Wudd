"""Core implementation for WuddSaveVideo."""
from fractions import Fraction
import hashlib
import json
import math
import os
import re
import subprocess
import uuid

import folder_paths

from .ffmpeg import resolve_ffmpeg_exe
from .common import WUDD_CATEGORY, CREATE_NO_WINDOW


def _video_index(name):
    try:
        return int(name.split("_", 1)[1])
    except (ValueError, IndexError):
        return 10 ** 9


def _collect_video_inputs(primary, extras):
    all_inputs = {"video_1": primary, **(extras or {})}
    items = [
        (key, value)
        for key, value in all_inputs.items()
        if key.startswith("video_") and value is not None
    ]
    items.sort(key=lambda item: _video_index(item[0]))
    return [value for _, value in items]

class WuddSaveVideo:
    _encoder_cache = {}

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_1": ("VIDEO",),
                "save_mode": (["append", "overwrite"], {"default": "append"}),
                "codec": (["av1", "h265"], {"default": "av1"}),
                "encoder": (["cpu", "nvidia", "intel", "amd"], {"default": "cpu"}),
                "container": (["mp4", "mkv"], {"default": "mp4"}),
                "crf": ("INT", {"default": 28, "min": 0, "max": 51, "step": 1}),
                "preset": (["fast", "medium", "slow"], {"default": "medium"}),
                "audio_mode": (["copy", "aac", "none"], {"default": "copy"}),
            },
            "optional": {
                "filename_prefix": ("STRING", {"default": "Wudd_Video"}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "save_videos"
    OUTPUT_NODE = True
    CATEGORY = WUDD_CATEGORY

    @staticmethod
    def _temp_path(suffix):
        temp_dir = folder_paths.get_temp_directory()
        os.makedirs(temp_dir, exist_ok=True)
        return os.path.join(temp_dir, f"wudd_{uuid.uuid4().hex}{suffix}")

    @staticmethod
    def _find_next_run(folder, filename, ext):
        pattern = re.compile(
            rf"^{re.escape(filename)}\.(\d+)\.\d+\.{re.escape(ext)}$",
            re.IGNORECASE,
        )
        max_n = 0
        try:
            for entry in os.scandir(folder):
                match = pattern.match(entry.name)
                if match:
                    max_n = max(max_n, int(match.group(1)))
        except OSError:
            pass
        return max_n + 1

    @staticmethod
    def _has_trim(video):
        start_time = float(getattr(video, "_VideoFromFile__start_time", 0) or 0)
        duration = float(getattr(video, "_VideoFromFile__duration", 0) or 0)
        return start_time != 0 or duration != 0

    @classmethod
    def _materialize_video_source(cls, video):
        if cls._has_trim(video) and hasattr(video, "save_to"):
            temp_input = cls._temp_path(".mp4")
            video.save_to(temp_input)
            return temp_input, temp_input

        if hasattr(video, "get_stream_source"):
            source = video.get_stream_source()
            if isinstance(source, (str, os.PathLike)):
                return os.fspath(source), None

            temp_input = cls._temp_path(".mp4")
            if hasattr(source, "seek"):
                source.seek(0)
            data = source.read() if hasattr(source, "read") else source
            with open(temp_input, "wb") as f:
                f.write(data)
            return temp_input, temp_input

        if hasattr(video, "save_to"):
            temp_input = cls._temp_path(".mp4")
            video.save_to(temp_input)
            return temp_input, temp_input

        raise TypeError("Unsupported VIDEO input: object cannot be saved or streamed.")

    @classmethod
    def _ffmpeg_encoders(cls, ffmpeg):
        if ffmpeg not in cls._encoder_cache:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                check=True,
                capture_output=True,
                text=True,
                shell=False,
                creationflags=CREATE_NO_WINDOW,
            )
            cls._encoder_cache[ffmpeg] = result.stdout
        return cls._encoder_cache[ffmpeg]

    @classmethod
    def _select_encoder(cls, ffmpeg, candidates, label):
        encoders = cls._ffmpeg_encoders(ffmpeg)
        for encoder in candidates:
            if encoder in encoders:
                return encoder
        raise RuntimeError(
            f"ffmpeg does not include a usable {label} encoder. "
            f"Tried: {', '.join(candidates)}"
        )

    @classmethod
    def _video_codec_args(cls, ffmpeg, codec, encoder_mode, container, crf, preset):
        crf = max(0, min(int(crf), 51))
        encoder_mode = encoder_mode or "cpu"

        if encoder_mode != "cpu":
            hardware_encoders = {
                "nvidia": {"av1": "av1_nvenc", "h265": "hevc_nvenc"},
                "intel": {"av1": "av1_qsv", "h265": "hevc_qsv"},
                "amd": {"av1": "av1_amf", "h265": "hevc_amf"},
            }
            try:
                encoder = hardware_encoders[encoder_mode][codec]
            except KeyError as e:
                raise ValueError(
                    f"Unsupported video encoder mode: {encoder_mode!r}"
                ) from e

            cls._select_encoder(ffmpeg, (encoder,), f"{encoder_mode} {codec.upper()}")

            if encoder_mode == "nvidia":
                preset_map = {"fast": "p3", "medium": "p5", "slow": "p7"}
                args = [
                    "-c:v", encoder,
                    "-preset", preset_map.get(preset, "p5"),
                    "-rc", "vbr",
                    "-cq", str(crf),
                    "-b:v", "0",
                    "-pix_fmt", "yuv420p",
                ]
            elif encoder_mode == "intel":
                preset_map = {"fast": "fast", "medium": "medium", "slow": "slow"}
                args = [
                    "-c:v", encoder,
                    "-preset", preset_map.get(preset, "medium"),
                    "-global_quality", str(crf),
                    "-pix_fmt", "nv12",
                ]
            else:
                quality_map = {"fast": "speed", "medium": "balanced", "slow": "quality"}
                args = [
                    "-c:v", encoder,
                    "-quality", quality_map.get(preset, "balanced"),
                    "-rc", "cqp",
                    "-qp_i", str(crf),
                    "-qp_p", str(crf),
                    "-pix_fmt", "yuv420p",
                ]

            if container == "mp4":
                args.extend(["-tag:v", "hvc1" if codec == "h265" else "av01"])
            return args

        if codec == "h265":
            encoder = cls._select_encoder(ffmpeg, ("libx265",), "H.265")
            args = [
                "-c:v", encoder,
                "-preset", preset,
                "-crf", str(crf),
                "-pix_fmt", "yuv420p",
            ]
            if container == "mp4":
                args.extend(["-tag:v", "hvc1"])
            return args

        encoder = cls._select_encoder(ffmpeg, ("libsvtav1", "libaom-av1"), "AV1")
        if encoder == "libsvtav1":
            preset_map = {"fast": "8", "medium": "6", "slow": "4"}
            args = [
                "-c:v", encoder,
                "-preset", preset_map.get(preset, "6"),
                "-crf", str(crf),
                "-pix_fmt", "yuv420p",
            ]
        else:
            cpu_used_map = {"fast": "6", "medium": "4", "slow": "2"}
            args = [
                "-c:v", encoder,
                "-cpu-used", cpu_used_map.get(preset, "4"),
                "-crf", str(crf),
                "-b:v", "0",
                "-pix_fmt", "yuv420p",
            ]
        if container == "mp4":
            args.extend(["-tag:v", "av01"])
        return args

    @staticmethod
    def _metadata_entries(prompt, extra_pnginfo):
        try:
            from comfy.cli_args import args as comfy_args
            if getattr(comfy_args, "disable_metadata", False):
                return []
        except Exception:
            pass

        metadata = []
        if prompt is not None:
            metadata.append(("prompt", json.dumps(prompt)))
        if extra_pnginfo is not None:
            for key, value in extra_pnginfo.items():
                metadata.append((str(key), json.dumps(value)))

        return metadata

    @staticmethod
    def _ffmetadata_escape(value):
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("\r\n", "\\n")
            .replace("\r", "\\n")
            .replace("\n", "\\n")
            .replace("=", "\\=")
            .replace(";", "\\;")
            .replace("#", "\\#")
        )

    @classmethod
    def _write_metadata_file(cls, metadata_entries):
        if not metadata_entries:
            return None

        metadata_path = cls._temp_path(".ffmetadata")
        with open(metadata_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(";FFMETADATA1\n")
            for key, value in metadata_entries:
                f.write(
                    f"{cls._ffmetadata_escape(key)}="
                    f"{cls._ffmetadata_escape(value)}\n"
                )
        return metadata_path

    @staticmethod
    def _first_audio_info(path):
        try:
            import av
            with av.open(path, mode="r") as container:
                audio_stream = next(
                    (stream for stream in container.streams if stream.type == "audio"),
                    None,
                )
                if audio_stream is None:
                    return None
                codec_context = audio_stream.codec_context
                sample_rate = codec_context.sample_rate
                channels = codec_context.channels
                bit_rate = getattr(codec_context, "bit_rate", None)
                if not bit_rate:
                    bit_rate = getattr(audio_stream, "bit_rate", None)
                return {
                    "codec": codec_context.name,
                    "sample_rate": int(sample_rate) if sample_rate else None,
                    "channels": int(channels) if channels else None,
                    "bit_rate": int(bit_rate) if bit_rate else None,
                }
        except Exception:
            return None

    @classmethod
    def _effective_audio_mode(cls, input_video, container, audio_mode, audio_info=None):
        if audio_mode != "copy" or container != "mp4":
            return audio_mode

        if audio_info is None:
            audio_info = cls._first_audio_info(input_video)
        codec = audio_info["codec"] if audio_info else None
        if codec is None or codec in {"aac", "mp3", "alac"}:
            return audio_mode

        print(
            f"[Wudd] Audio codec {codec} cannot be copied safely into MP4; "
            "encoding final audio as AAC."
        )
        return "aac"

    @staticmethod
    def _aac_audio_args(audio_info):
        args = ["-c:a", "aac"]
        if audio_info:
            sample_rate = audio_info.get("sample_rate")
            channels = audio_info.get("channels")
            if sample_rate:
                args.extend(["-ar", str(sample_rate)])
            if channels:
                args.extend(["-ac", str(channels)])
        return args

    @classmethod
    def _run_ffmpeg(cls, input_video, output_path, codec, encoder_mode, container,
                    crf, preset, audio_mode, metadata_entries):
        ffmpeg = resolve_ffmpeg_exe()
        audio_info = cls._first_audio_info(input_video)
        audio_mode = cls._effective_audio_mode(
            input_video,
            container,
            audio_mode,
            audio_info,
        )

        metadata_path = cls._write_metadata_file(metadata_entries)
        try:
            cmd = [
                ffmpeg,
                "-y",
                "-i", input_video,
            ]

            if metadata_path:
                cmd.extend(["-f", "ffmetadata", "-i", metadata_path])

            cmd.extend(["-map", "0:v:0"])

            if audio_mode != "none":
                cmd.extend(["-map", "0:a?"])

            cmd.extend(["-map_metadata", "0"])
            if metadata_path:
                cmd.extend(["-map_metadata", "1"])
            cmd.extend(cls._video_codec_args(
                ffmpeg,
                codec,
                encoder_mode,
                container,
                crf,
                preset,
            ))

            if audio_mode == "copy":
                cmd.extend(["-c:a", "copy"])
            elif audio_mode == "aac":
                cmd.extend(cls._aac_audio_args(audio_info))
            else:
                cmd.append("-an")

            if container == "mp4":
                cmd.extend(["-movflags", "+faststart"])

            cmd.append(output_path)

            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                shell=False,
                creationflags=CREATE_NO_WINDOW,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or e.stdout or "").strip()
            raise RuntimeError(
                f"ffmpeg failed while saving {codec.upper()} video: {stderr or e}"
            ) from e
        except FileNotFoundError as e:
            if getattr(e, "winerror", None) == 206:
                raise RuntimeError(
                    "Windows refused to start ffmpeg because a command-line path is "
                    "too long. Shorten the output directory or filename prefix."
                ) from e
            raise
        finally:
            try:
                if metadata_path and os.path.exists(metadata_path):
                    os.remove(metadata_path)
            except OSError:
                pass

    @staticmethod
    def _video_dimensions(video):
        try:
            width, height = video.get_dimensions()
            return int(width), int(height)
        except Exception:
            return 0, 0

    @staticmethod
    def _append_run_is_free(folder, filename, ext, run, count):
        for seq in range(1, count + 1):
            file_name = f"{filename}.{run:05}.{seq:02}.{ext}"
            if os.path.exists(os.path.join(folder, file_name)):
                return False
        return True

    def save_videos(self, video_1, filename_prefix="Wudd_Video", save_mode="append",
                    codec="av1", encoder="cpu", container="mp4", crf=28,
                    preset="medium", audio_mode="copy", audio_bitrate=None,
                    prompt=None, extra_pnginfo=None, **kwargs):
        videos = _collect_video_inputs(video_1, kwargs)
        if not videos:
            return {"ui": {"images": [], "animated": (True,)}}

        width, height = self._video_dimensions(videos[0])
        full_output_folder, filename, _, subfolder, filename_prefix = \
            folder_paths.get_save_image_path(filename_prefix, self.output_dir,
                                             width, height)

        ext = container
        total_videos = len(videos)
        if save_mode == "append":
            run = self._find_next_run(full_output_folder, filename, ext)
            while not self._append_run_is_free(
                full_output_folder, filename, ext, run, total_videos
            ):
                run += 1

        metadata_entries = self._metadata_entries(prompt, extra_pnginfo)
        results = []

        for seq, video in enumerate(videos, start=1):
            if save_mode == "overwrite":
                if total_videos == 1:
                    file_name = f"{filename}.{ext}"
                else:
                    file_name = f"{filename}.{seq:02}.{ext}"
            else:
                file_name = f"{filename}.{run:05}.{seq:02}.{ext}"

            output_path = os.path.join(full_output_folder, file_name)
            cleanup_paths = []

            try:
                input_video, temp_input = self._materialize_video_source(video)
                if temp_input:
                    cleanup_paths.append(temp_input)
                self._run_ffmpeg(
                    input_video,
                    output_path,
                    codec,
                    encoder,
                    container,
                    crf,
                    preset,
                    audio_mode,
                    metadata_entries,
                )
            finally:
                for path in cleanup_paths:
                    try:
                        if path and os.path.exists(path):
                            os.remove(path)
                    except OSError:
                        pass

            results.append({
                "filename": file_name,
                "subfolder": subfolder,
                "type": self.type,
            })

        return {"ui": {"images": results, "animated": (True,)}}

__all__ = [
    "WuddSaveVideo",
    "_collect_video_inputs",
]

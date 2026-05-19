"""
ComfyUI-Wudd - video nodes.

Contains:
    WuddSaveVideo        Save one or more VIDEO inputs with AV1 or H.265 encoding
    WuddFastForwardVideo Speed up a VIDEO input by multiplier or target duration
    WuddConcatVideos     Concatenate VIDEO inputs in input order
"""

from fractions import Fraction
import hashlib
import json
import math
import os
import re
import subprocess
import uuid

import folder_paths

from .nodes_audio import resolve_ffmpeg_exe
from .nodes_common import WUDD_CATEGORY, CREATE_NO_WINDOW


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


class WuddConcatVideos:
    CACHE_VERSION = "v1"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_1": ("VIDEO",),
                "video_2": ("VIDEO",),
                "resize_mode": (["fit_to_first", "stretch_to_first"], {"default": "fit_to_first"}),
                "audio_mode": (["keep", "none"], {"default": "keep"}),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "concat_videos"
    CATEGORY = WUDD_CATEGORY

    @staticmethod
    def _cache_dir():
        cache_dir = os.path.join(
            folder_paths.get_temp_directory(),
            "video",
            "wudd_concat_cache",
        )
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    @classmethod
    def _cache_path(cls, stem, suffix):
        return os.path.join(cls._cache_dir(), f"{stem}_{uuid.uuid4().hex}{suffix}")

    @staticmethod
    def _file_signature(path):
        stat = os.stat(path)
        return {
            "path": os.path.abspath(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    @classmethod
    def _segment_cache_path(cls, input_path, index, width, height, fps,
                            resize_mode, audio_mode, pix_fmt,
                            audio_sample_rate, audio_channels, audio_layout):
        payload = {
            "version": cls.CACHE_VERSION,
            "input": cls._file_signature(input_path),
            "index": index,
            "width": width,
            "height": height,
            "fps": fps,
            "resize_mode": resize_mode,
            "audio_mode": audio_mode,
            "pix_fmt": pix_fmt,
            "audio_sample_rate": audio_sample_rate,
            "audio_channels": audio_channels,
            "audio_layout": audio_layout,
        }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()[:24]
        return os.path.join(cls._cache_dir(), f"segment_{index:02}_{digest}.mkv")

    @staticmethod
    def _usable_cache(path):
        try:
            return os.path.exists(path) and os.path.getsize(path) > 0
        except OSError:
            return False

    @staticmethod
    def _fps_string(video):
        try:
            fps = video.get_frame_rate()
        except Exception:
            fps = None

        if fps is None:
            try:
                fps = video.get_components().frame_rate
            except Exception:
                fps = Fraction(24, 1)

        if isinstance(fps, Fraction):
            rate = fps
        else:
            rate = Fraction(float(fps)).limit_denominator(1001)

        if rate <= 0:
            rate = Fraction(24, 1)
        return f"{rate.numerator}/{rate.denominator}"

    @staticmethod
    def _even_dimension(value):
        value = max(2, int(value))
        return value if value % 2 == 0 else value + 1

    @staticmethod
    def _probe_has_audio(path):
        import av

        with av.open(path, mode="r") as container:
            return len(container.streams.audio) > 0

    @staticmethod
    def _probe_video_pix_fmt(path):
        import av

        with av.open(path, mode="r") as container:
            video_stream = next(
                (stream for stream in container.streams if stream.type == "video"),
                None,
            )
            if video_stream is None:
                return "yuv420p"
            pix_fmt = getattr(video_stream.codec_context, "pix_fmt", None)
            return pix_fmt or "yuv420p"

    @staticmethod
    def _audio_layout_for_channels(channels):
        return {
            1: "mono",
            2: "stereo",
            6: "5.1",
            8: "7.1",
        }.get(channels, "stereo")

    @classmethod
    def _probe_audio_settings(cls, path):
        import av

        with av.open(path, mode="r") as container:
            audio_stream = next(
                (stream for stream in container.streams if stream.type == "audio"),
                None,
            )
            if audio_stream is None:
                return 48000, 2, "stereo"

            sample_rate = int(audio_stream.codec_context.sample_rate or 48000)
            channels = int(audio_stream.codec_context.channels or 2)
            return sample_rate, channels, cls._audio_layout_for_channels(channels)

    @staticmethod
    def _probe_duration(path):
        import av

        with av.open(path, mode="r") as container:
            if container.duration is not None:
                return max(0.001, float(container.duration / av.time_base))

            video_stream = next(
                (stream for stream in container.streams if stream.type == "video"),
                None,
            )
            if video_stream is not None:
                if video_stream.duration is not None and video_stream.time_base is not None:
                    return max(0.001, float(video_stream.duration * video_stream.time_base))
                if video_stream.frames and video_stream.average_rate:
                    return max(0.001, float(video_stream.frames / video_stream.average_rate))

        return 0.001

    @staticmethod
    def _concat_file_line(path):
        safe_path = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
        return f"file '{safe_path}'\n"

    @staticmethod
    def _resize_filter(width, height, fps, resize_mode):
        if resize_mode == "stretch_to_first":
            return f"scale={width}:{height},fps={fps},setsar=1"

        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},setsar=1"
        )

    @classmethod
    def _normalize_segment(cls, ffmpeg, input_path, output_path, width, height, fps,
                           resize_mode, audio_mode, pix_fmt, audio_sample_rate,
                           audio_channels, audio_layout):
        has_audio = cls._probe_has_audio(input_path)
        duration = cls._probe_duration(input_path)
        vf = f"{cls._resize_filter(width, height, fps, resize_mode)},format={pix_fmt}"

        cmd = [
            ffmpeg,
            "-y",
            "-i", input_path,
        ]

        if audio_mode == "keep" and not has_audio:
            cmd.extend([
                "-f", "lavfi",
                "-t", f"{duration:.6f}",
                "-i", f"anullsrc=channel_layout={audio_layout}:sample_rate={audio_sample_rate}",
            ])

        cmd.extend([
            "-map", "0:v:0",
            "-vf", vf,
            "-c:v", "ffv1",
            "-level", "3",
            "-g", "1",
            "-slices", "16",
            "-slicecrc", "1",
        ])

        if audio_mode == "none":
            cmd.append("-an")
        elif has_audio:
            cmd.extend([
                "-map", "0:a:0",
                "-c:a", "pcm_f32le",
                "-ar", str(audio_sample_rate),
                "-ac", str(audio_channels),
                "-af", "apad",
            ])
        else:
            cmd.extend([
                "-map", "1:a:0",
                "-c:a", "pcm_f32le",
                "-ar", str(audio_sample_rate),
                "-ac", str(audio_channels),
            ])

        cmd.extend(["-t", f"{duration:.6f}"])
        cmd.append(output_path)

        try:
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
                f"ffmpeg failed while preparing video segment for concat: {stderr or e}"
            ) from e

    @classmethod
    def _normalize_segment_cached(cls, ffmpeg, input_path, index, width, height, fps,
                                  resize_mode, audio_mode, pix_fmt,
                                  audio_sample_rate, audio_channels, audio_layout):
        cache_path = cls._segment_cache_path(
            input_path,
            index,
            width,
            height,
            fps,
            resize_mode,
            audio_mode,
            pix_fmt,
            audio_sample_rate,
            audio_channels,
            audio_layout,
        )
        if cls._usable_cache(cache_path):
            return cache_path

        staging_path = cls._cache_path(f"segment_{index:02}_staging", ".mkv")
        try:
            cls._normalize_segment(
                ffmpeg,
                input_path,
                staging_path,
                width,
                height,
                fps,
                resize_mode,
                audio_mode,
                pix_fmt,
                audio_sample_rate,
                audio_channels,
                audio_layout,
            )
            os.replace(staging_path, cache_path)
            return cache_path
        finally:
            try:
                if os.path.exists(staging_path):
                    os.remove(staging_path)
            except OSError:
                pass

    @classmethod
    def _mp4_video_args(cls, ffmpeg):
        try:
            encoder = WuddSaveVideo._select_encoder(
                ffmpeg,
                ("libx264",),
                "H.264 MP4",
            )
            return [
                "-c:v", encoder,
                "-preset", "veryfast",
                "-crf", "16",
                "-pix_fmt", "yuv420p",
            ]
        except RuntimeError:
            encoder = WuddSaveVideo._select_encoder(
                ffmpeg,
                ("mpeg4",),
                "MP4 video",
            )
            return [
                "-c:v", encoder,
                "-q:v", "2",
                "-pix_fmt", "yuv420p",
            ]

    @classmethod
    def _concat_segments(cls, ffmpeg, segment_paths, output_path):
        list_path = WuddSaveVideo._temp_path(".txt")
        try:
            with open(list_path, "w", encoding="utf-8", newline="\n") as f:
                for path in segment_paths:
                    f.write(cls._concat_file_line(path))

            cmd = [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_path,
                "-map", "0:v:0",
                "-map", "0:a?",
                *cls._mp4_video_args(ffmpeg),
                "-c:a", "aac",
                "-b:a", "320k",
                "-movflags", "+faststart",
                "-f", "mp4",
                output_path,
            ]
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
                f"ffmpeg failed while concatenating video segments: {stderr or e}"
            ) from e
        finally:
            try:
                if os.path.exists(list_path):
                    os.remove(list_path)
            except OSError:
                pass

    def concat_videos(self, video_1, video_2=None, resize_mode="fit_to_first",
                      audio_mode="keep", **kwargs):
        from comfy_api.latest import InputImpl

        videos = _collect_video_inputs(video_1, {"video_2": video_2, **kwargs})
        if len(videos) < 2:
            return (video_1,)

        ffmpeg = resolve_ffmpeg_exe()
        width, height = WuddSaveVideo._video_dimensions(videos[0])
        width = self._even_dimension(width)
        height = self._even_dimension(height)
        fps = self._fps_string(videos[0])

        output_path = self._cache_path("concat_output", ".mp4")
        cleanup_paths = []
        segment_paths = []

        try:
            pix_fmt = None
            audio_sample_rate = None
            audio_channels = None
            audio_layout = None

            for index, video in enumerate(videos, start=1):
                input_path, temp_input = WuddSaveVideo._materialize_video_source(video)
                if temp_input:
                    cleanup_paths.append(temp_input)

                if index == 1:
                    pix_fmt = self._probe_video_pix_fmt(input_path)
                    audio_sample_rate, audio_channels, audio_layout = \
                        self._probe_audio_settings(input_path)

                segment_path = self._normalize_segment_cached(
                    ffmpeg,
                    input_path,
                    index,
                    width,
                    height,
                    fps,
                    resize_mode,
                    audio_mode,
                    pix_fmt,
                    audio_sample_rate,
                    audio_channels,
                    audio_layout,
                )
                segment_paths.append(segment_path)

            self._concat_segments(ffmpeg, segment_paths, output_path)
            return (InputImpl.VideoFromFile(output_path),)
        finally:
            for path in cleanup_paths:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass


class WuddFastForwardVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "mode": (["speed_multiplier", "target_seconds"], {"default": "speed_multiplier"}),
                "speed_multiplier": ("FLOAT", {"default": 2.0, "min": 0.01, "max": 100.0, "step": 0.01}),
                "target_seconds": ("FLOAT", {"default": 5.0, "min": 0.001, "max": 86400.0, "step": 0.001}),
                "audio_mode": (["keep", "none"], {"default": "keep"}),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "fast_forward_video"
    CATEGORY = WUDD_CATEGORY

    @staticmethod
    def _validate_speed(speed):
        speed = float(speed)
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed_multiplier must be a positive finite number.")
        return speed

    @staticmethod
    def _float_expr(value):
        return f"{float(value):.12g}"

    @staticmethod
    def _probe_duration(path):
        import av

        with av.open(path, mode="r") as container:
            if container.duration is not None:
                return max(0.001, float(container.duration / av.time_base))

            video_stream = next(
                (stream for stream in container.streams if stream.type == "video"),
                None,
            )
            if video_stream is not None:
                if video_stream.duration is not None and video_stream.time_base is not None:
                    return max(0.001, float(video_stream.duration * video_stream.time_base))
                if video_stream.frames and video_stream.average_rate:
                    return max(0.001, float(video_stream.frames / video_stream.average_rate))

        raise ValueError("Could not determine video duration for target_seconds mode.")

    @classmethod
    def _speed_from_inputs(cls, input_path, mode, speed_multiplier, target_seconds):
        if mode == "target_seconds":
            target_seconds = float(target_seconds)
            if not math.isfinite(target_seconds) or target_seconds <= 0:
                raise ValueError("target_seconds must be a positive finite number.")
            speed = cls._validate_speed(cls._probe_duration(input_path) / target_seconds)
            return speed, target_seconds
        return cls._validate_speed(speed_multiplier), None

    @classmethod
    def _atempo_filter(cls, speed):
        remaining = cls._validate_speed(speed)
        factors = []

        while remaining > 2.0:
            factors.append(2.0)
            remaining /= 2.0

        while remaining < 0.5:
            factors.append(0.5)
            remaining /= 0.5

        factors.append(remaining)
        return ",".join(f"atempo={cls._float_expr(factor)}" for factor in factors)

    @classmethod
    def _run_ffmpeg(cls, ffmpeg, input_path, output_path, speed, audio_mode,
                    target_seconds=None):
        speed_expr = cls._float_expr(speed)
        vf = (
            f"setpts=(PTS-STARTPTS)/{speed_expr},"
            "scale=ceil(iw/2)*2:ceil(ih/2)*2,setsar=1"
        )
        audio_info = WuddSaveVideo._first_audio_info(input_path)

        cmd = [
            ffmpeg,
            "-y",
            "-i", input_path,
            "-map", "0:v:0",
            "-vf", vf,
            *WuddConcatVideos._mp4_video_args(ffmpeg),
        ]

        if audio_mode == "keep" and audio_info is not None:
            af = f"asetpts=PTS-STARTPTS,{cls._atempo_filter(speed)}"
            cmd.extend([
                "-map", "0:a:0",
                "-af", af,
                *WuddSaveVideo._aac_audio_args(audio_info),
                "-shortest",
            ])
        else:
            cmd.append("-an")

        if target_seconds is not None:
            cmd.extend(["-t", cls._float_expr(target_seconds)])

        cmd.extend([
            "-movflags", "+faststart",
            "-f", "mp4",
            output_path,
        ])

        try:
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
                f"ffmpeg failed while fast-forwarding video: {stderr or e}"
            ) from e

    def fast_forward_video(self, video, mode="speed_multiplier", speed_multiplier=2.0,
                           target_seconds=5.0, audio_mode="keep"):
        from comfy_api.latest import InputImpl

        ffmpeg = resolve_ffmpeg_exe()
        input_path, temp_input = WuddSaveVideo._materialize_video_source(video)
        output_path = WuddSaveVideo._temp_path(".mp4")

        try:
            speed, target_duration = self._speed_from_inputs(
                input_path,
                mode,
                speed_multiplier,
                target_seconds,
            )
            self._run_ffmpeg(
                ffmpeg,
                input_path,
                output_path,
                speed,
                audio_mode,
                target_duration,
            )
            return (InputImpl.VideoFromFile(output_path),)
        finally:
            try:
                if temp_input and os.path.exists(temp_input):
                    os.remove(temp_input)
            except OSError:
                pass

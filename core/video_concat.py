"""Core implementation for WuddConcatVideos."""
from fractions import Fraction
import hashlib
import json
import math
import os
import re
import subprocess
import uuid

import folder_paths

from .common import WUDD_CATEGORY, CREATE_NO_WINDOW
from .ffmpeg import resolve_ffmpeg_exe
from .video_common import (
    _collect_video_inputs,
    _materialize_video_source,
    _select_encoder,
    _temp_path,
    _video_dimensions,
)


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
            encoder = _select_encoder(
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
            encoder = _select_encoder(
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
        list_path = _temp_path(".txt")
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
        width, height = _video_dimensions(videos[0])
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
                input_path, temp_input = _materialize_video_source(video)
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

__all__ = [
    "WuddConcatVideos",
]

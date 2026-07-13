"""Core implementation for WuddFastForwardVideo."""
import math
import os
import subprocess

from .common import CREATE_NO_WINDOW
from .ffmpeg import resolve_ffmpeg_exe
from .video_common import (
    _aac_audio_args,
    _first_audio_info,
    _materialize_video_source,
    _mp4_video_args,
    _temp_path,
)

class WuddFastForwardVideo:
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
        audio_info = _first_audio_info(input_path)

        cmd = [
            ffmpeg,
            "-y",
            "-i", input_path,
            "-map", "0:v:0",
            "-vf", vf,
            *_mp4_video_args(ffmpeg),
        ]

        if audio_mode == "keep" and audio_info is not None:
            af = f"asetpts=PTS-STARTPTS,{cls._atempo_filter(speed)}"
            cmd.extend([
                "-map", "0:a:0",
                "-af", af,
                *_aac_audio_args(audio_info),
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
        input_path, temp_input = _materialize_video_source(video)
        output_path = _temp_path(".mp4")

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

__all__ = [
    "WuddFastForwardVideo",
]

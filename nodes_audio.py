"""
ComfyUI-Wudd — 音频类节点。

包含：
    WuddVideoAudioExtractor  从 VIDEO 输入中提取 ComfyUI AUDIO
    WuddReplaceVideoAudio    用 AUDIO 替换 VIDEO 中的音频轨
"""

import os
import shutil
import subprocess
import uuid

import folder_paths

from .nodes_common import WUDD_CATEGORY, CREATE_NO_WINDOW


NODE_DIR = os.path.dirname(__file__)
LOCAL_BIN_DIR = os.path.join(NODE_DIR, "bin")


def _local_ffmpeg_names():
    ext = ".exe" if os.name == "nt" else ""
    return tuple(f"{name}{ext}" for name in ("ffmpeg", "ffprobe", "ffplay"))


def resolve_ffmpeg_exe():
    """Resolve an ffmpeg binary without exposing path configuration in the node UI."""
    local_bin_names = _local_ffmpeg_names()
    local_bin_paths = [os.path.join(LOCAL_BIN_DIR, name) for name in local_bin_names]
    if all(os.path.isfile(path) for path in local_bin_paths):
        return os.path.join(LOCAL_BIN_DIR, local_bin_names[0])

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass

    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    raise FileNotFoundError(
        "ffmpeg executable not found. Install this custom node's requirements "
        "with ComfyUI Python, or place a complete ffmpeg/ffprobe/ffplay set "
        "under ComfyUI-Wudd/bin/."
    )


class WuddVideoAudioExtractor:
    @staticmethod
    def _f32_pcm(wav):
        if wav.dtype.is_floating_point:
            return wav.float()
        if str(wav.dtype) == "torch.int16":
            return wav.float() / (2 ** 15)
        if str(wav.dtype) == "torch.int32":
            return wav.float() / (2 ** 31)
        raise ValueError(f"Unsupported audio dtype: {wav.dtype}")

    @classmethod
    def _decode_audio(cls, video_source, audio_stream_index):
        import av
        import torch

        if hasattr(video_source, "seek"):
            video_source.seek(0)

        with av.open(video_source) as container:
            audio_streams = list(container.streams.audio)
            if not audio_streams:
                raise ValueError("No audio stream found in video.")

            stream_index = max(0, min(int(audio_stream_index), len(audio_streams) - 1))
            stream = audio_streams[stream_index]
            sample_rate = stream.codec_context.sample_rate
            channels = stream.channels

            frames = []
            for frame in container.decode(stream):
                buf = torch.from_numpy(frame.to_ndarray())
                if buf.shape[0] != channels:
                    buf = buf.view(-1, channels).t()
                frames.append(buf)

            if not frames:
                raise ValueError("No audio frames decoded from video.")

            waveform = cls._f32_pcm(torch.cat(frames, dim=1)).unsqueeze(0)
            duration = waveform.shape[-1] / float(sample_rate)
            return {"waveform": waveform, "sample_rate": sample_rate}, sample_rate, duration

    @staticmethod
    def _apply_video_trim(audio, video):
        start_time = float(getattr(video, "_VideoFromFile__start_time", 0) or 0)
        duration = float(getattr(video, "_VideoFromFile__duration", 0) or 0)
        if start_time <= 0 and duration <= 0:
            return audio

        sample_rate = int(audio["sample_rate"])
        waveform = audio["waveform"]
        audio_duration = waveform.shape[-1] / float(sample_rate)
        if start_time < 0:
            start_time = max(0.0, audio_duration + start_time)
        start_sample = max(0, int(round(start_time * sample_rate)))
        end_sample = None
        if duration > 0:
            end_sample = start_sample + max(0, int(round(duration * sample_rate)))
        return {
            "waveform": waveform[..., start_sample:end_sample],
            "sample_rate": sample_rate,
        }

    @classmethod
    def _extract_from_video(cls, video, audio_stream_index):
        if hasattr(video, "get_stream_source"):
            audio, _, _ = cls._decode_audio(video.get_stream_source(), audio_stream_index)
            audio = cls._apply_video_trim(audio, video)
            duration = audio["waveform"].shape[-1] / float(audio["sample_rate"])
            return audio, int(audio["sample_rate"]), duration

        components = video.get_components()
        if not components.audio:
            raise ValueError("No audio stream found in video.")
        audio = {
            "waveform": components.audio["waveform"],
            "sample_rate": int(components.audio["sample_rate"]),
        }
        duration = audio["waveform"].shape[-1] / float(audio["sample_rate"])
        return audio, int(audio["sample_rate"]), duration

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "audio_stream_index": ("INT", {"default": 0, "min": 0, "max": 16, "step": 1}),
            },
        }

    RETURN_TYPES = ("AUDIO", "INT", "FLOAT")
    RETURN_NAMES = ("audio", "sample_rate", "duration_seconds")
    FUNCTION = "extract_audio"
    CATEGORY = WUDD_CATEGORY

    @classmethod
    def IS_CHANGED(cls, video, audio_stream_index=0):
        source = video.get_stream_source() if hasattr(video, "get_stream_source") else None
        if isinstance(source, str) and os.path.isfile(source):
            return f"{source}:{os.path.getmtime(source)}:{audio_stream_index}"
        return float("NaN")

    def extract_audio(self, video, audio_stream_index=0):
        audio, sample_rate, duration = self._extract_from_video(video, audio_stream_index)
        return (audio, sample_rate, duration)


class WuddReplaceVideoAudio:
    @staticmethod
    def _temp_path(suffix):
        temp_dir = folder_paths.get_temp_directory()
        os.makedirs(temp_dir, exist_ok=True)
        return os.path.join(temp_dir, f"wudd_{uuid.uuid4().hex}{suffix}")

    @staticmethod
    def _write_audio_wav(audio, path):
        import wave
        import numpy as np

        waveform = audio["waveform"]
        if waveform.ndim == 3:
            waveform = waveform[0]
        pcm = waveform.detach().cpu().float().clamp(-1.0, 1.0).numpy()
        pcm = (pcm * 32767.0).astype(np.int16)
        channels, samples = pcm.shape
        interleaved = pcm.T.reshape(samples * channels)

        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(audio["sample_rate"]))
            wav_file.writeframes(interleaved.tobytes())

    @staticmethod
    def _materialize_video_source(video):
        source = video.get_stream_source()
        if isinstance(source, str):
            return source, None

        temp_input = WuddReplaceVideoAudio._temp_path(".mp4")
        if hasattr(source, "seek"):
            source.seek(0)
        with open(temp_input, "wb") as f:
            f.write(source.read())
        return temp_input, temp_input

    @staticmethod
    def _probe_video_duration(path):
        import av

        with av.open(path, mode="r") as container:
            video_stream = next(
                (stream for stream in container.streams if stream.type == "video"),
                None,
            )
            if video_stream is not None:
                if video_stream.duration is not None and video_stream.time_base is not None:
                    return max(0.001, float(video_stream.duration * video_stream.time_base))
                if video_stream.frames and video_stream.average_rate:
                    return max(0.001, float(video_stream.frames / video_stream.average_rate))

            if container.duration is not None:
                return max(0.001, float(container.duration / av.time_base))

        return 0.001

    @classmethod
    def _video_timing(cls, video, input_video):
        start_time = float(getattr(video, "_VideoFromFile__start_time", 0) or 0)
        duration = float(getattr(video, "_VideoFromFile__duration", 0) or 0)
        source_duration = cls._probe_video_duration(input_video)

        if start_time < 0:
            start_time = max(0.0, source_duration + start_time)
        else:
            start_time = max(0.0, start_time)

        if duration <= 0:
            duration = max(0.001, source_duration - start_time)

        return start_time, duration

    @staticmethod
    def _fallback_components(video, audio):
        from fractions import Fraction
        from comfy_api.latest import InputImpl, Types

        components = video.get_components()
        return InputImpl.VideoFromComponents(Types.VideoComponents(
            images=components.images,
            audio=audio,
            frame_rate=Fraction(components.frame_rate),
            metadata=getattr(components, "metadata", None),
        ))

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "audio": ("AUDIO",),
                "output_format": (["mp4", "mkv", "mov"], {"default": "mp4"}),
                "audio_bitrate": (["128k", "192k", "256k", "320k"], {"default": "192k"}),
                # "shortest" is accepted for older workflows, but both modes
                # now keep output duration aligned to the video stream.
                "end_mode": (["keep_video_length", "shortest"], {"default": "keep_video_length"}),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "replace_audio"
    CATEGORY = WUDD_CATEGORY

    def replace_audio(self, video, audio, output_format="mp4", audio_bitrate="192k",
                      end_mode="shortest"):
        from comfy_api.latest import InputImpl

        if not hasattr(video, "get_stream_source"):
            return (self._fallback_components(video, audio),)

        ffmpeg = resolve_ffmpeg_exe()
        audio_wav = self._temp_path(".wav")
        output_path = self._temp_path(f".{output_format}")
        cleanup_paths = [audio_wav]

        try:
            input_video, temp_input = self._materialize_video_source(video)
            if temp_input:
                cleanup_paths.append(temp_input)
            start_time, video_duration = self._video_timing(video, input_video)
            self._write_audio_wav(audio, audio_wav)

            cmd = [
                ffmpeg,
                "-y",
            ]
            if start_time > 0:
                cmd.extend(["-ss", f"{start_time:.6f}"])
            cmd.extend([
                "-i", input_video,
                "-i", audio_wav,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", audio_bitrate,
                "-af", "apad",
                "-t", f"{video_duration:.6f}",
            ])
            if output_format in ("mp4", "mov"):
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
            return (InputImpl.VideoFromFile(output_path),)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            raise RuntimeError(f"ffmpeg failed while replacing video audio: {stderr or e}") from e
        finally:
            for path in cleanup_paths:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

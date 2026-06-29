"""Shared video helpers used by separate video execution implementations."""

import os
import subprocess
import uuid

import folder_paths

from .common import CREATE_NO_WINDOW


_ENCODER_CACHE = {}


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


def _temp_path(suffix):
    temp_dir = folder_paths.get_temp_directory()
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, f"wudd_{uuid.uuid4().hex}{suffix}")


def _has_trim(video):
    start_time = float(getattr(video, "_VideoFromFile__start_time", 0) or 0)
    duration = float(getattr(video, "_VideoFromFile__duration", 0) or 0)
    return start_time != 0 or duration != 0


def _materialize_video_source(video):
    if _has_trim(video) and hasattr(video, "save_to"):
        temp_input = _temp_path(".mp4")
        video.save_to(temp_input)
        return temp_input, temp_input

    if hasattr(video, "get_stream_source"):
        source = video.get_stream_source()
        if isinstance(source, (str, os.PathLike)):
            return os.fspath(source), None

        temp_input = _temp_path(".mp4")
        if hasattr(source, "seek"):
            source.seek(0)
        data = source.read() if hasattr(source, "read") else source
        with open(temp_input, "wb") as f:
            f.write(data)
        return temp_input, temp_input

    if hasattr(video, "save_to"):
        temp_input = _temp_path(".mp4")
        video.save_to(temp_input)
        return temp_input, temp_input

    raise TypeError("Unsupported VIDEO input: object cannot be saved or streamed.")


def _ffmpeg_encoders(ffmpeg):
    if ffmpeg not in _ENCODER_CACHE:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            creationflags=CREATE_NO_WINDOW,
        )
        _ENCODER_CACHE[ffmpeg] = result.stdout
    return _ENCODER_CACHE[ffmpeg]


def _select_encoder(ffmpeg, candidates, label):
    encoders = _ffmpeg_encoders(ffmpeg)
    for encoder in candidates:
        if encoder in encoders:
            return encoder
    raise RuntimeError(
        f"ffmpeg does not include a usable {label} encoder. "
        f"Tried: {', '.join(candidates)}"
    )


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


def _video_dimensions(video):
    try:
        width, height = video.get_dimensions()
        return int(width), int(height)
    except Exception:
        return 0, 0


def _mp4_video_args(ffmpeg):
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


__all__ = [
    "_aac_audio_args",
    "_collect_video_inputs",
    "_first_audio_info",
    "_materialize_video_source",
    "_mp4_video_args",
    "_select_encoder",
    "_temp_path",
    "_video_dimensions",
]

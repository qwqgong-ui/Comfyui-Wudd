"""Shared ffmpeg binary resolution."""
import os
import shutil


PACKAGE_DIR = os.path.dirname(os.path.dirname(__file__))
LOCAL_BIN_DIR = os.path.join(PACKAGE_DIR, "bin")


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



__all__ = [
    "resolve_ffmpeg_exe",
]

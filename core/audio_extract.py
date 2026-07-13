"""Core implementation for WuddVideoAudioExtractor."""
import os

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
    def IS_CHANGED(cls, video, audio_stream_index=0):
        source = video.get_stream_source() if hasattr(video, "get_stream_source") else None
        if isinstance(source, str) and os.path.isfile(source):
            return f"{source}:{os.path.getmtime(source)}:{audio_stream_index}"
        return float("NaN")

    def extract_audio(self, video, audio_stream_index=0):
        audio, sample_rate, duration = self._extract_from_video(video, audio_stream_index)
        return (audio, sample_rate, duration)

__all__ = [
    "WuddVideoAudioExtractor",
]

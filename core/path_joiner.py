"""Core implementation for WuddPathJoiner."""
class WuddPathJoiner:
    def join_path(self, count, segment_1, segment_2, segment_3, segment_4, segment_5):
        all_segments = [segment_1, segment_2, segment_3, segment_4, segment_5]
        parts = [s for s in all_segments[:count] if s.strip()]
        return ("/".join(parts),)

__all__ = [
    "WuddPathJoiner",
]

"""Shared image helpers used by separate image execution implementations."""

import numpy as np


def _parse_hex_color(hex_str):
    """'#RRGGBB' -> (r, g, b) float 0-1; invalid input returns middle gray."""
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = s[0] * 2 + s[1] * 2 + s[2] * 2
    if len(s) != 6:
        return (0.5, 0.5, 0.5)
    try:
        return (
            int(s[0:2], 16) / 255.0,
            int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0,
        )
    except ValueError:
        return (0.5, 0.5, 0.5)


def _make_checkerboard(height, width, tile_size):
    """Build a checkerboard RGB background as [H, W, 3] float32."""
    c1 = np.array([0.80, 0.80, 0.80], dtype=np.float32)
    c2 = np.array([0.55, 0.55, 0.55], dtype=np.float32)
    rows = np.arange(height) // tile_size
    cols = np.arange(width) // tile_size
    pattern = (rows[:, None] + cols[None, :]) % 2
    return np.where(pattern[:, :, None] == 0, c1, c2)


__all__ = ["_make_checkerboard", "_parse_hex_color"]

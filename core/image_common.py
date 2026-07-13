"""Shared image helpers used by separate image execution implementations."""

import torch


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


def _make_checkerboard(height, width, tile_size, *, device=None, dtype=None):
    """Build a checkerboard directly on the target Torch device."""
    dtype = dtype or torch.float32
    rows = torch.arange(height, device=device) // tile_size
    cols = torch.arange(width, device=device) // tile_size
    pattern = (rows[:, None] + cols[None, :]).remainder_(2)

    # The previous NumPy implementation created float32 colors before casting
    # to the input dtype. Preserve that order for exact float64/float16 values.
    colors = torch.tensor(
        ((0.80, 0.80, 0.80), (0.55, 0.55, 0.55)),
        device=device,
        dtype=torch.float32,
    ).to(dtype=dtype)
    return colors[pattern]


__all__ = ["_make_checkerboard", "_parse_hex_color"]

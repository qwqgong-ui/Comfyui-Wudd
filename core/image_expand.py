"""Core implementation for WuddImageExpand."""
from .image_common import _make_checkerboard, _parse_hex_color

class WuddImageExpand:
    """
    将原图朝指定方向扩展 N 个"原图大小"的填充区域。
    填充模式与 WuddDropAlpha 一致：棋盘格 或 纯色。
    输出扩展后的图像以及最终宽高。
    """

    def expand(self, image, direction, count, mode, fill_color, tile_size):
        import torch

        B, H, W, C = image.shape

        # 构造一个原图大小的填充块 [B, H, W, C]
        if mode == "checkerboard":
            block = _make_checkerboard(
                H,
                W,
                tile_size,
                device=image.device,
                dtype=image.dtype,
            )
            if C == 4:
                alpha = torch.ones((H, W, 1), device=image.device, dtype=image.dtype)
                block = torch.cat([block, alpha], dim=-1)
            block = block.unsqueeze(0).expand(B, -1, -1, -1)
        else:  # fill_color
            r, g, b = _parse_hex_color(fill_color)
            channels = [r, g, b, 1.0] if C == 4 else [r, g, b]
            block = torch.tensor(channels, dtype=image.dtype,
                                 device=image.device).view(1, 1, 1, C).expand(B, H, W, C)

        # 横向 dim=2，纵向 dim=1
        horizontal = direction in ("right", "left")
        axis = 2 if horizontal else 1
        blocks = [block] * count

        if direction in ("right", "down"):
            result = torch.cat([image] + blocks, dim=axis)
        else:  # left / up
            result = torch.cat(blocks + [image], dim=axis)

        out_h = result.shape[1]
        out_w = result.shape[2]
        return (result, out_w, out_h)

__all__ = [
    "WuddImageExpand",
]

"""Core implementation for WuddDropAlpha."""
import os
import re
import sys
import json
import uuid
import shutil
import subprocess
import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import folder_paths

from .common import (
    WUDD_CATEGORY,
    CREATE_NO_WINDOW,
    collect_image_inputs,
    tensor_to_pil,
    pil_to_tensor,
)

class WuddDropAlpha:
    """
    用背景替换透明区域，丢掉 alpha 遮罩，输出不透明 RGB 图像。
    mask 未连接或全为不透明时直通。
    背景可选棋盘格或纯色填充，可选按内容区域自动裁剪。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (["checkerboard", "fill_color"],),
                "fill_color": ("STRING", {"default": "#808080"}),
                "tile_size": ("INT", {"default": 16, "min": 4, "max": 128, "step": 4}),
                "auto_crop": ("BOOLEAN", {"default": False}),
                "padding": ("INT", {"default": 0, "min": 0, "max": 2048}),
            },
            "optional": {
                # MASK 形状：[B, H, W]，值 1=透明，0=不透明
                "mask": ("MASK",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "drop_alpha"
    CATEGORY = WUDD_CATEGORY

    @staticmethod
    def _parse_hex_color(hex_str):
        """'#RRGGBB' → (r, g, b) float 0-1，解析失败返回中灰。"""
        s = hex_str.strip().lstrip("#")
        if len(s) == 3:
            s = s[0]*2 + s[1]*2 + s[2]*2
        if len(s) != 6:
            return (0.5, 0.5, 0.5)
        try:
            return (int(s[0:2], 16) / 255.0,
                    int(s[2:4], 16) / 255.0,
                    int(s[4:6], 16) / 255.0)
        except ValueError:
            return (0.5, 0.5, 0.5)

    @staticmethod
    def _make_checkerboard(H, W, tile_size):
        """生成棋盘格背景 [H, W, 3] float32，浅灰/深灰交替。"""
        c1 = np.array([0.80, 0.80, 0.80], dtype=np.float32)
        c2 = np.array([0.55, 0.55, 0.55], dtype=np.float32)
        rows = np.arange(H) // tile_size
        cols = np.arange(W) // tile_size
        pattern = (rows[:, None] + cols[None, :]) % 2  # [H, W]，0 或 1
        return np.where(pattern[:, :, None] == 0, c1, c2)  # [H, W, 3]

    @staticmethod
    def _crop_bounds(mask_np, padding, H, W):
        """
        mask_np: [B, H, W]，0=不透明内容区域
        返回跨 batch 取并集后加 padding 的裁剪范围 (y1, y2, x1, x2)。
        全透明时返回完整图像尺寸。
        """
        content = mask_np < 0.5               # [B, H, W] bool，True=有内容
        union   = content.any(axis=0)         # [H, W]
        row_any = union.any(axis=1)           # [H]
        col_any = union.any(axis=0)           # [W]

        if not row_any.any():
            return 0, H, 0, W

        y1 = int(np.argmax(row_any))
        y2 = int(H - np.argmax(row_any[::-1]))
        x1 = int(np.argmax(col_any))
        x2 = int(W - np.argmax(col_any[::-1]))

        y1 = max(0, y1 - padding)
        y2 = min(H, y2 + padding)
        x1 = max(0, x1 - padding)
        x2 = min(W, x2 + padding)
        return y1, y2, x1, x2

    def drop_alpha(self, image, mode, fill_color, tile_size,
                   auto_crop=False, padding=0, mask=None):
        import torch

        # mask 未连接 → 直通
        if mask is None:
            return (image,)

        # mask 全为不透明 → 直通
        if mask.max().item() <= 1e-5:
            return (image,)

        # mask: [B, H, W] → [B, H, W, 1] 以便广播
        alpha = mask.unsqueeze(-1).to(image.dtype).to(image.device)

        B, H, W, _ = image.shape

        if mode == "checkerboard":
            board = self._make_checkerboard(H, W, tile_size)
            bg = torch.from_numpy(board).to(image.device)
            bg = bg.unsqueeze(0).expand(B, -1, -1, -1)               # [B, H, W, 3]
        else:  # fill_color
            r, g, b = self._parse_hex_color(fill_color)
            bg = torch.tensor([r, g, b], dtype=image.dtype,
                              device=image.device).view(1, 1, 1, 3).expand(B, H, W, -1)

        # mask 在 ComfyUI 中 1=透明，0=不透明
        result = (image * (1.0 - alpha) + bg * alpha).clamp(0.0, 1.0)

        if auto_crop:
            y1, y2, x1, x2 = self._crop_bounds(
                mask.cpu().numpy(), padding, H, W
            )
            result = result[:, y1:y2, x1:x2, :]

        return (result,)

__all__ = [
    "WuddDropAlpha",
]

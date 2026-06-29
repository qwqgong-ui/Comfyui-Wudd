"""Core implementation for WuddImageStitch."""
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

class WuddImageStitch:
    """
    线性图像拼接节点。
    image_1 作为基准图，image_2~16 按顺序向同一方向拼接。
    所有图自动适配第一张图在拼接轴上的尺寸（保持各自宽高比缩放）。
    """

    MAX_INPUTS = 16

    @classmethod
    def INPUT_TYPES(cls):
        required = {
            "image_1":   ("IMAGE",),
            "direction": (["right", "down", "left", "up"], {"default": "right"}),
            "gap":       ("INT", {"default": 0, "min": 0, "max": 256, "step": 1}),
            "input_count": ("INT", {"default": 2, "min": 1, "max": cls.MAX_INPUTS, "step": 1}),
        }
        optional = {
            f"image_{i}": ("IMAGE",) for i in range(2, cls.MAX_INPUTS + 1)
        }
        return {"required": required, "optional": optional}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION     = "stitch"
    CATEGORY     = WUDD_CATEGORY

    # ── 工具函数 ──────────────────────────────────────────────────────

    def _fit_height(self, img, target_h):
        """缩放图像使高度=target_h，宽度等比例变化。"""
        pil  = tensor_to_pil(img)
        w, h = pil.size
        new_w = max(1, round(w * target_h / h))
        return pil_to_tensor(pil.resize((new_w, target_h), Image.LANCZOS))

    def _fit_width(self, img, target_w):
        """缩放图像使宽度=target_w，高度等比例变化。"""
        pil  = tensor_to_pil(img)
        w, h = pil.size
        new_h = max(1, round(h * target_w / w))
        return pil_to_tensor(pil.resize((target_w, new_h), Image.LANCZOS))

    # ── 主逻辑 ────────────────────────────────────────────────────────

    def stitch(self, image_1, direction, gap, input_count, **kwargs):
        import torch

        # 收集所有有效图像（按编号顺序），受 input_count 限制
        max_inputs = max(1, min(int(input_count), self.MAX_INPUTS))
        images = collect_image_inputs(image_1, kwargs, max_n=max_inputs)

        if len(images) == 1:
            return (image_1,)

        _, ref_h, ref_w, C = image_1.shape
        horizontal = direction in ("right", "left")

        # 适配所有图像到第一张的基准边长
        scaled = []
        for img in images:
            if horizontal:
                # 左右拼接 → 统一高度
                scaled.append(self._fit_height(img, ref_h))
            else:
                # 上下拼接 → 统一宽度
                scaled.append(self._fit_width(img, ref_w))

        # left/up 方向：把 2~N 图倒序排在 image_1 前面
        if direction in ("left", "up"):
            tail = list(reversed(scaled[1:]))
            ordered = tail + [scaled[0]]
        else:  # right / down
            ordered = scaled

        # 拼接
        result = ordered[0]
        for nxt in ordered[1:]:
            if horizontal:
                if gap > 0:
                    h_now = result.shape[1]
                    bar = torch.zeros(
                        (1, h_now, gap, C),
                        device=result.device, dtype=result.dtype
                    )
                    result = torch.cat([result, bar, nxt], dim=2)
                else:
                    result = torch.cat([result, nxt], dim=2)
            else:
                if gap > 0:
                    w_now = result.shape[2]
                    bar = torch.zeros(
                        (1, gap, w_now, C),
                        device=result.device, dtype=result.dtype
                    )
                    result = torch.cat([result, bar, nxt], dim=1)
                else:
                    result = torch.cat([result, nxt], dim=1)

        return (result,)

__all__ = [
    "WuddImageStitch",
]

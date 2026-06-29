"""Core implementation for WuddEdgePad."""
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

class WuddEdgePad:
    """
    多图输入版竖向全景预处理节点。
    核心思路：把相邻两图的真实边缘内容拼在一起做高斯模糊，
    自然融合后分别作为两图的扩充 pad，彻底消除纯色色带。
    原图上下边沿做 smoothstep 倒角，pad/图衔接处再做一次模糊。
    """

    MAX_INPUTS = 16

    @classmethod
    def INPUT_TYPES(cls):
        required = {
            "image_1":    ("IMAGE",),
            "pad_px":     ("INT",   {"default": 100,  "min": 10,  "max": 500,  "step": 1}),
            "blend_pct":  ("FLOAT", {"default": 3.0,  "min": 0.5, "max": 20.0, "step": 0.5,
                                     "tooltip": "pad/图衔接带占图高百分比（两侧各此值）"}),
            "pad_sigma":  ("FLOAT", {"default": 30.0, "min": 1.0, "max": 200.0,"step": 1.0,
                                     "tooltip": "跨图混合高斯模糊强度（越大色带越不明显）"}),
            "blend_sigma":("FLOAT", {"default": 12.0, "min": 1.0, "max": 80.0, "step": 0.5,
                                     "tooltip": "pad/图衔接带的额外模糊强度"}),
            "chamfer_pct":("FLOAT", {"default": 20.0, "min": 0.0, "max": 80.0, "step": 1.0,
                                     "tooltip": "原图上下边沿倒角深度（占图高百分比，0=关闭）"}),
        }
        optional = {f"image_{i}": ("IMAGE",) for i in range(2, cls.MAX_INPUTS + 1)}
        return {"required": required, "optional": optional}

    RETURN_TYPES  = ("IMAGE",) * MAX_INPUTS
    RETURN_NAMES  = tuple(f"image_{i}" for i in range(1, MAX_INPUTS + 1))
    FUNCTION      = "pad_edges"
    CATEGORY      = WUDD_CATEGORY

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _chamfer(arr, ch):
        """
        原图顶/底各 ch 行做 smoothstep 倒角，渐变混入该侧的平均色。
        就地修改，返回所用平均色供后续使用。
        """
        if ch <= 0:
            H = arr.shape[0]
            sr = max(1, H // 16)
            top_c = arr[:sr].mean(axis=(0, 1))
            bot_c = arr[H - sr:].mean(axis=(0, 1))
            return top_c, bot_c
        H = arr.shape[0]
        sr = max(1, ch)
        top_c = arr[:sr].mean(axis=(0, 1)).astype(np.float32)
        bot_c = arr[H - sr:].mean(axis=(0, 1)).astype(np.float32)
        t = np.linspace(0.0, 1.0, ch, dtype=np.float32).reshape(ch, 1, 1)
        a = t * t * (3.0 - 2.0 * t)
        arr[:ch]     = arr[:ch]     * a + top_c * (1.0 - a)
        arr[H - ch:] = arr[H - ch:] * a[::-1] + bot_c * (1.0 - a[::-1])
        return top_c, bot_c

    @staticmethod
    def _cross_blend_pad(a_bot_rows, b_top_rows, pad_px, sigma):
        """
        把 a 的底部行与 b 的顶部行拼合后做高斯模糊，
        返回 (a的底部扩充pad, b的顶部扩充pad)，shape均为 [pad_px, W, C]。
        拼接边界两侧取自同一个模糊数组，颜色天然连续无跳变。
        """
        from scipy.ndimage import gaussian_filter
        combined = np.concatenate([a_bot_rows, b_top_rows], axis=0).astype(np.float64)
        blurred  = gaussian_filter(combined, sigma=[sigma, sigma * 0.3, 0]).astype(np.float32)
        return blurred[:pad_px], blurred[pad_px:]

    @staticmethod
    def _edge_pad(edge_rows, pad_px, sigma, outward=True):
        """
        首/末图的外侧 pad：将边缘内容镜像后模糊，给出自然过渡。
        outward=True 表示向外延伸（top 方向用镜像；bot 方向用镜像）。
        """
        from scipy.ndimage import gaussian_filter
        mirrored = edge_rows[::-1].copy()            # 镜像边缘内容
        blurred  = gaussian_filter(
            mirrored.astype(np.float64), sigma=[sigma, sigma * 0.3, 0]
        ).astype(np.float32)
        return blurred[:pad_px]

    @staticmethod
    def _blend_junctions(canvas, pad_px, H, br, sigma):
        """在 pad/图两个衔接点做余弦钟形权重 × 高斯模糊（就地）。"""
        from scipy.ndimage import gaussian_filter
        TH = canvas.shape[0]
        blurred = gaussian_filter(
            canvas.astype(np.float64), sigma=[sigma, sigma * 0.3, 0]
        ).astype(np.float32)
        weight = np.zeros(TH, dtype=np.float32)
        for j in (pad_px, pad_px + H):
            r0 = max(0, j - br)
            r1 = min(TH, j + br)
            idxs = np.arange(r0, r1, dtype=np.float32)
            t    = (idxs - j) / br
            w    = 0.5 * (1.0 + np.cos(t * np.pi))
            weight[r0:r1] = np.maximum(weight[r0:r1], w)
        weight = weight.reshape(TH, 1, 1)
        return canvas * (1.0 - weight) + blurred * weight

    # ------------------------------------------------------------------ main

    def pad_edges(self, image_1, pad_px, blend_pct, pad_sigma,
                  blend_sigma, chamfer_pct, **kwargs):
        import torch

        tensors = collect_image_inputs(image_1, kwargs)
        arrs = [t[0].cpu().numpy().copy().astype(np.float32) for t in tensors]
        N = len(arrs)

        # ── 第一步：预先计算每张图的 top_pad / bot_pad ──────────────────────
        top_pads = [None] * N
        bot_pads = [None] * N

        for i in range(N):
            H, W, C = arrs[i].shape
            grab = min(pad_px, H)           # 取多少行参与混合

            if i == 0:
                # 第一张顶部：镜像自身顶部内容向外模糊
                top_pads[0] = self._edge_pad(arrs[0][:grab], pad_px, pad_sigma)
            if i == N - 1:
                # 最后一张底部：镜像自身底部内容向外模糊
                bot_pads[N - 1] = self._edge_pad(arrs[N-1][-grab:], pad_px, pad_sigma)

            if i < N - 1:
                # 相邻两图的跨图混合 pad
                grab_i  = min(pad_px, arrs[i].shape[0])
                grab_i1 = min(pad_px, arrs[i + 1].shape[0])
                a_bot = arrs[i    ][-grab_i :]
                b_top = arrs[i + 1][: grab_i1]
                bot_pads[i], top_pads[i + 1] = self._cross_blend_pad(
                    a_bot, b_top, pad_px, pad_sigma
                )

        # ── 第二步：对每张图做倒角 + 拼接 + 衔接模糊 ────────────────────────
        results_np = []
        for i, arr in enumerate(arrs):
            H, W, C = arr.shape
            ch = max(0, int(H * chamfer_pct / 100.0))
            br = max(2, int(H * blend_pct   / 100.0))

            self._chamfer(arr, ch)          # 倒角（就地）

            canvas = np.concatenate([top_pads[i], arr, bot_pads[i]], axis=0)
            canvas = self._blend_junctions(canvas, pad_px, H, br, blend_sigma)
            results_np.append(np.clip(canvas, 0.0, 1.0))

        # ── 补齐输出槽 ────────────────────────────────────────────────────────
        empty = np.zeros((1, 1, 3), dtype=np.float32)
        out = []
        for i in range(self.MAX_INPUTS):
            arr = results_np[i] if i < N else empty
            out.append(torch.from_numpy(arr).unsqueeze(0))
        return tuple(out)

__all__ = [
    "WuddEdgePad",
]

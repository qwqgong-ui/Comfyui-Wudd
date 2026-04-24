"""
ComfyUI-Wudd — 节点实现模块。

本文件负责实现节点的运行时行为；节点"规范层"（CATEGORY、输入/输出约定、
共享工具函数）在本模块顶部集中声明，便于审阅、一致性校验以及未来扩展。

规范层 / 实现层分工：
    规范层  → WUDD_CATEGORY、_image_index、collect_image_inputs、
              tensor_to_pil、pil_to_tensor、tensor_to_base64_png、CREATE_NO_WINDOW
    实现层  → 每个节点类内部的算法方法（_chamfer、_wait_for_response 等）

说明文档：`ai_skill.md`（节点逻辑总览）。
"""

import os
import re
import sys
import json
import uuid
import time
import base64
import subprocess
import ssl
import http.client
import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from io import BytesIO
from urllib.parse import urljoin, urlparse
import folder_paths


# ──────────────────────────────────────────────────────────────────────────
# 模块级规范层：所有 Wudd 节点的共享常量与工具函数
# ──────────────────────────────────────────────────────────────────────────

# 所有节点在 ComfyUI 菜单下的统一分类名；集中声明，重命名只改一处。
WUDD_CATEGORY = "Wudd Nodes"

# Windows 下隐藏 cjpegli 弹出的黑框；非 Windows 上此 flag 为 0（no-op）。
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# `collect_image_inputs` 中缺失索引时的"放到最后"哨兵值。
_IMAGE_INDEX_SENTINEL = 10 ** 9


def _image_index(name):
    """从 'image_N' 风格的键里抽取数字索引；缺失/非法时回退到末尾哨兵值。"""
    try:
        return int(name.split("_", 1)[1])
    except (ValueError, IndexError):
        return _IMAGE_INDEX_SENTINEL


def collect_image_inputs(primary, extras, max_n=None):
    """
    合并 `image_1`（primary）与 `image_*`（extras kwargs）并按数字索引排序，
    过滤掉 None 值。可选 max_n 限制上界（例如 input_count）。
    返回 list[tensor]，按 image_1 → image_2 → … 顺序。
    """
    all_inputs = {"image_1": primary, **(extras or {})}
    items = [(k, v) for k, v in all_inputs.items()
             if k.startswith("image_") and v is not None]
    items.sort(key=lambda kv: _image_index(kv[0]))
    if max_n is not None:
        items = [(k, v) for k, v in items if _image_index(k) <= max_n]
    return [v for _, v in items]


def tensor_to_pil(image_tensor):
    """
    ComfyUI IMAGE 单帧 → PIL 图像。
    接受 [H, W, C] 或 [1, H, W, C] 两种形状；C=3 → RGB，C=4 → RGBA。
    """
    arr = image_tensor
    if arr.ndim == 4:
        arr = arr[0]
    img_np = (255.0 * arr.cpu().numpy()).clip(0, 255).astype(np.uint8)
    mode = "RGBA" if img_np.shape[-1] == 4 else "RGB"
    return Image.fromarray(img_np, mode=mode)


def pil_to_tensor(pil_img):
    """PIL 图像 → ComfyUI IMAGE 单帧，形状 [1, H, W, C]，float32，值域 [0,1]。"""
    import torch
    arr = np.array(pil_img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def tensor_to_base64_png(image_tensor):
    """ComfyUI IMAGE 单帧 → base64 PNG 字符串（用于 data URL 内联）。"""
    buffer = BytesIO()
    tensor_to_pil(image_tensor).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# ──────────────────────────────────────────────────────────────────────────
# 节点实现
# ──────────────────────────────────────────────────────────────────────────


class WuddMultiSaveImage:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        exe_name = "cjpegli.exe" if sys.platform == "win32" else "cjpegli"
        self.cjpegli_exe = os.path.join(
            os.path.dirname(__file__), "jxl-x64-windows-static", "bin", exe_name
        )
        self.cjpegli_available = os.path.isfile(self.cjpegli_exe)
        if not self.cjpegli_available:
            print(f"[Wudd] cjpegli not found at {self.cjpegli_exe}; "
                  f"jpegli mode will fall back to PIL JPEG.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_1": ("IMAGE",),
                "save_mode": (["append", "overwrite"],),
                "extension": (["png", "jpegli"],),
                "quality": ("INT", {"default": 90, "min": 1, "max": 100}),
                "progressive": ("BOOLEAN", {"default": True}),
                "enable_xyb": ("BOOLEAN", {"default": False}),
                "chroma_subsampling": (["444", "440", "422", "420"],),
            },
            "optional": {
                # optional 使得该 widget 既保留输入框，又可直接接 STRING 节点
                "filename_prefix": ("STRING", {"default": "Wudd_Img"}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = WUDD_CATEGORY

    # ---------- helpers ----------

    @staticmethod
    def _find_next_run(folder, filename, ext):
        """扫描追加模式的已有文件 {filename}.NNNNN.NN.{ext}，返回下一批次编号。"""
        pattern = re.compile(
            rf"^{re.escape(filename)}\.(\d+)\.\d+\.{re.escape(ext)}$",
            re.IGNORECASE,
        )
        max_n = 0
        try:
            for entry in os.scandir(folder):
                m = pattern.match(entry.name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
        except OSError:
            pass
        return max_n + 1

    @staticmethod
    def _build_pnginfo(prompt, extra_pnginfo):
        """镜像 ComfyUI 默认 SaveImage 的元数据写入，保证 PNG 能拖回还原工作流。"""
        metadata = PngInfo()
        if prompt is not None:
            metadata.add_text("prompt", json.dumps(prompt))
        if extra_pnginfo is not None:
            for k, v in extra_pnginfo.items():
                metadata.add_text(k, json.dumps(v))
        return metadata

    def _run_cjpegli(self, src_png, dst_jpg, quality, progressive,
                     enable_xyb, chroma_subsampling):
        cmd = [
            self.cjpegli_exe, src_png, dst_jpg,
            "--quality", str(quality),
            "-p", "2" if progressive else "0",
            f"--chroma_subsampling={chroma_subsampling}",
        ]
        if enable_xyb:
            cmd.append("--xyb")
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            creationflags=CREATE_NO_WINDOW,
        )

    def _pil_jpeg_fallback(self, img_pil, file_path, quality, progressive,
                           chroma_subsampling, reason):
        print(f"[Wudd] Falling back to PIL JPEG ({reason}): "
              f"{os.path.basename(file_path)}")
        save_kwargs = {
            "quality": quality,
            "progressive": bool(progressive),
            "optimize": True,
        }
        sub_map = {"444": 0, "422": 1, "420": 2}
        if chroma_subsampling in sub_map:
            save_kwargs["subsampling"] = sub_map[chroma_subsampling]
        img_pil.save(file_path, **save_kwargs)

    def _save_jpegli(self, img_pil, file_path, folder, quality, progressive,
                     enable_xyb, chroma_subsampling):
        if not self.cjpegli_available:
            self._pil_jpeg_fallback(img_pil, file_path, quality, progressive,
                                    chroma_subsampling, "cjpegli not available")
            return

        temp_png = os.path.join(folder, f".tmp_{uuid.uuid4().hex}.png")
        try:
            img_pil.save(temp_png)
            self._run_cjpegli(temp_png, file_path, quality, progressive,
                              enable_xyb, chroma_subsampling)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            print(f"[Wudd] cjpegli failed: {stderr or e}")
            self._pil_jpeg_fallback(img_pil, file_path, quality, progressive,
                                    chroma_subsampling, "cjpegli error")
        except (FileNotFoundError, OSError) as e:
            print(f"[Wudd] cjpegli not runnable: {e}")
            self._pil_jpeg_fallback(img_pil, file_path, quality, progressive,
                                    chroma_subsampling, "cjpegli unavailable")
        finally:
            if os.path.exists(temp_png):
                try:
                    os.remove(temp_png)
                except OSError:
                    pass

    def _do_save(self, img_pil, file_path, extension, png_metadata,
                 folder, quality, progressive, enable_xyb, chroma_subsampling):
        if extension == "png":
            img_pil.save(file_path, pnginfo=png_metadata, compress_level=4)
        else:
            self._save_jpegli(img_pil, file_path, folder,
                              quality, progressive, enable_xyb, chroma_subsampling)

    # ---------- main entry ----------

    def save_images(self, image_1, filename_prefix="Wudd_Img", save_mode="append",
                    extension="png", quality=90, progressive=True, enable_xyb=False,
                    chroma_subsampling="444", prompt=None, extra_pnginfo=None,
                    **kwargs):
        height, width = image_1.shape[1], image_1.shape[2]
        # get_save_image_path 仅用于文件夹解析和 %width%/%year% 等占位符替换
        full_output_folder, filename, _, subfolder, filename_prefix = \
            folder_paths.get_save_image_path(filename_prefix, self.output_dir,
                                             width, height)

        ext = "jpg" if extension == "jpegli" else "png"

        # 合并并按编号排序所有图像输入
        tensors = collect_image_inputs(image_1, kwargs)

        # 统计本次调用的图像总数，用于覆盖模式的命名判断
        total_images = sum(len(t) for t in tensors)

        png_metadata = (self._build_pnginfo(prompt, extra_pnginfo)
                        if extension == "png" else None)

        # 追加模式：确定本次批次编号（扫描已有文件取最大值 +1）
        if save_mode == "append":
            run = self._find_next_run(full_output_folder, filename, ext)

        results = []
        seq = 0  # 本次调用内的图像序号（1-based）

        for images in tensors:
            for image in images:
                seq += 1
                img_pil = tensor_to_pil(image)

                if save_mode == "overwrite":
                    # 覆盖模式：文件名固定，每次运行都写同一批文件
                    # 单图：{前缀}.{ext}；多图：{前缀}.{序号:02}.{ext}
                    if total_images == 1:
                        file_name = f"{filename}.{ext}"
                    else:
                        file_name = f"{filename}.{seq:02}.{ext}"

                else:
                    # 追加模式：{前缀}.{批次:05}.{序号:02}.{ext}
                    file_name = f"{filename}.{run:05}.{seq:02}.{ext}"
                    # 双重保险：若文件意外存在则跳到下一批次
                    file_path = os.path.join(full_output_folder, file_name)
                    if os.path.exists(file_path):
                        run += 1
                        file_name = f"{filename}.{run:05}.{seq:02}.{ext}"

                file_path = os.path.join(full_output_folder, file_name)
                self._do_save(img_pil, file_path, extension, png_metadata,
                              full_output_folder, quality, progressive,
                              enable_xyb, chroma_subsampling)

                results.append({
                    "filename": file_name,
                    "subfolder": subfolder,
                    "type": self.type,
                })

        return {"ui": {"images": results}}


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


class WuddPathJoiner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "count":     ("INT",    {"default": 2, "min": 1, "max": 5}),
                "segment_1": ("STRING", {"default": ""}),
                "segment_2": ("STRING", {"default": ""}),
                "segment_3": ("STRING", {"default": ""}),
                "segment_4": ("STRING", {"default": ""}),
                "segment_5": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("path",)
    FUNCTION = "join_path"
    CATEGORY = WUDD_CATEGORY

    def join_path(self, count, segment_1, segment_2, segment_3, segment_4, segment_5):
        all_segments = [segment_1, segment_2, segment_3, segment_4, segment_5]
        parts = [s for s in all_segments[:count] if s.strip()]
        return ("/".join(parts),)


class WuddTextSplitter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "index": ("INT", {"default": 0, "min": 0, "max": 99999}),
                "skip_empty": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "split_text"
    CATEGORY = WUDD_CATEGORY

    def split_text(self, text, index, skip_empty=False):
        lines = text.splitlines()
        if skip_empty:
            lines = [line for line in lines if line.strip()]
        if 0 <= index < len(lines):
            return (lines[index],)
        return ("",)


class WuddMultiTextSplitter:
    MAX_OUTPUTS = 16  # JS 端同步保持此上限

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "count": ("INT", {"default": 2, "min": 1, "max": cls.MAX_OUTPUTS}),
                "skip_empty": ("BOOLEAN", {"default": False}),
            }
        }

    # 固定声明最大数量；JS 动态隐藏多余的输出槽
    RETURN_TYPES = ("STRING",) * MAX_OUTPUTS
    RETURN_NAMES = tuple(f"line_{i}" for i in range(MAX_OUTPUTS))
    FUNCTION = "split_text"
    CATEGORY = WUDD_CATEGORY

    def split_text(self, text, count, skip_empty=False):
        lines = text.splitlines()
        if skip_empty:
            lines = [line for line in lines if line.strip()]
        # 返回恰好 MAX_OUTPUTS 个值；超出 count 的槽只是空字符串，前端不连接即可
        return tuple(lines[i] if i < len(lines) else "" for i in range(self.MAX_OUTPUTS))


class WuddImageListImporter:
    MAX_IMAGES = 50

    @classmethod
    def _list_input_files(cls):
        """列出 ComfyUI input 目录下的文件；目录缺失/不可读时返回占位 ['none']。"""
        input_dir = folder_paths.get_input_directory()
        try:
            files = [f for f in os.listdir(input_dir)
                     if os.path.isfile(os.path.join(input_dir, f))]
        except OSError:
            files = []
        return files if files else ["none"]

    @classmethod
    def INPUT_TYPES(cls):
        files = cls._list_input_files()
        inputs = {
            "required": {
                "image_count": ("INT", {"default": 1, "min": 1, "max": cls.MAX_IMAGES, "step": 1}),
            },
            "optional": {},
        }
        for i in range(1, cls.MAX_IMAGES + 1):
            inputs["required"][f"image_{i}"] = (files, {"image_upload": True})
        return inputs

    @classmethod
    def IS_CHANGED(cls, image_count, **kwargs):
        """
        文件系统依赖节点的正确缓存键：文件名 + 该文件的 mtime。
        避免"同一文件名但磁盘内容已更新"时工作流误命中旧缓存。
        """
        parts = [str(image_count)]
        for i in range(1, cls.MAX_IMAGES + 1):
            if i > image_count:
                continue
            name = kwargs.get(f"image_{i}", "")
            parts.append(str(name))
            if name and name != "none":
                try:
                    path = folder_paths.get_annotated_filepath(name)
                    if os.path.exists(path):
                        parts.append(str(os.path.getmtime(path)))
                except Exception:
                    pass
        return "|".join(parts)

    RETURN_TYPES = tuple(["IMAGE"] * MAX_IMAGES)
    RETURN_NAMES = tuple([f"image_{i}" for i in range(1, MAX_IMAGES + 1)])
    FUNCTION = "import_images"
    CATEGORY = WUDD_CATEGORY

    def import_images(self, image_count, **kwargs):
        import torch
        from PIL import ImageOps
        images = []
        for i in range(1, self.MAX_IMAGES + 1):
            if i > image_count:
                images.append(None)
                continue

            image_name = kwargs.get(f"image_{i}")
            if image_name and image_name != "none":
                image_path = folder_paths.get_annotated_filepath(image_name)
                if os.path.exists(image_path):
                    try:
                        i_img = Image.open(image_path)
                        i_img = ImageOps.exif_transpose(i_img)
                        images.append(pil_to_tensor(i_img.convert("RGB")))
                    except Exception as e:
                        print(f"[WuddImageListImporter] Error loading image {image_name}: {e}")
                        # Fallback empty image
                        images.append(torch.zeros((1, 64, 64, 3)))
                else:
                    images.append(torch.zeros((1, 64, 64, 3)))
            else:
                images.append(torch.zeros((1, 64, 64, 3)))

        return tuple(images)


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


class WuddOpenAIGPT54:
    RESPONSES_URL = "https://api.openai.com/v1/responses"
    CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": ""}),
                "base_url": ("STRING", {"default": "https://api.openai.com/v1"}),
                "model": ("STRING", {"default": "gpt-5.4"}),
                "api_mode": (["responses", "chat_completions"], {"default": "responses"}),
                "reasoning_effort": (["none", "low", "medium", "high", "xhigh"], {"default": "medium"}),
                "verbosity": (["low", "medium", "high"], {"default": "medium"}),
                "verify_ssl": ("BOOLEAN", {"default": True}),
                "max_output_tokens": ("INT", {"default": 4096, "min": 16, "max": 131072}),
                "poll_interval": ("FLOAT", {"default": 1.0, "min": 0.2, "max": 10.0, "step": 0.1}),
                "max_wait_seconds": ("INT", {"default": 120, "min": 5, "max": 3600}),
            },
            "optional": {
                "instructions": ("STRING", {"default": "", "multiline": True}),
                "images": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "response_id")
    FUNCTION = "generate"
    CATEGORY = "Wudd Nodes"

    @staticmethod
    def _validate_api_key(api_key):
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("OpenAI API key is required.")
        return api_key

    @staticmethod
    def _normalize_base_url(base_url):
        base_url = (base_url or "").strip()
        if not base_url:
            return "https://api.openai.com/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        return base_url.rstrip("/")

    @classmethod
    def _build_endpoint(cls, base_url, api_mode, response_id=None):
        if api_mode == "chat_completions":
            return urljoin(base_url + "/", "chat/completions")
        endpoint = urljoin(base_url + "/", "responses")
        if response_id:
            endpoint = f"{endpoint}/{response_id}"
        return endpoint

    @staticmethod
    def _tensor_to_base64_png(image_tensor):
        image_np = (255.0 * image_tensor.cpu().numpy()).clip(0, 255).astype(np.uint8)
        if image_np.shape[-1] == 4:
            mode = "RGBA"
        else:
            mode = "RGB"
        img = Image.fromarray(image_np, mode=mode)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @classmethod
    def _build_input_content(cls, prompt, images=None):
        content = [{"type": "input_text", "text": prompt}]
        if images is not None:
            for i in range(images.shape[0]):
                content.append(
                    {
                        "type": "input_image",
                        "detail": "auto",
                        "image_url": f"data:image/png;base64,{cls._tensor_to_base64_png(images[i])}",
                    }
                )
        return [{"role": "user", "content": content}]

    @staticmethod
    def _extract_text(response_json, api_mode):
        if api_mode == "chat_completions":
            choices = response_json.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                content = message.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    return "".join(text_parts)
            return ""

        output_text = response_json.get("output_text")
        if output_text:
            return output_text

        output = response_json.get("output", [])
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return content.get("text", "")
        return ""

    @staticmethod
    def _http_json(url, api_key, payload=None, method="POST", timeout=300, verify_ssl=True):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {url}")

        ssl_context = None
        if not verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        conn = None
        try:
            if parsed.scheme == "https":
                conn = connection_cls(parsed.hostname, port, timeout=timeout, context=ssl_context)
            else:
                conn = connection_cls(parsed.hostname, port, timeout=timeout)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw_body = resp.read().decode("utf-8", errors="replace")
        except ssl.SSLError as e:
            raise ValueError(f"SSL error while reaching OpenAI-compatible API: {e}") from e
        except OSError as e:
            raise ValueError(f"Failed to reach OpenAI-compatible API: {e}") from e
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

        if resp.status >= 400:
            raise ValueError(f"OpenAI API error {resp.status}: {raw_body}")

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as e:
            raise ValueError(f"OpenAI API returned invalid JSON: {raw_body}") from e

    @classmethod
    def _wait_for_response(cls, api_key, base_url, response_id, poll_interval, max_wait_seconds, verify_ssl):
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            response_json = cls._http_json(
                cls._build_endpoint(base_url, "responses", response_id),
                api_key,
                payload=None,
                method="GET",
                timeout=max(30, int(poll_interval * 10)),
                verify_ssl=verify_ssl,
            )
            status = response_json.get("status")
            if status in ("completed", "incomplete"):
                return response_json
            if status in ("failed", "cancelled", "canceled"):
                raise ValueError(f"OpenAI response failed with status '{status}': {json.dumps(response_json, ensure_ascii=False)}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Timed out waiting for OpenAI response after {max_wait_seconds} seconds.")

    def generate(
        self,
        prompt,
        api_key,
        base_url,
        model,
        api_mode,
        reasoning_effort,
        verbosity,
        verify_ssl,
        max_output_tokens,
        poll_interval,
        max_wait_seconds,
        instructions="",
        images=None,
    ):
        api_key = self._validate_api_key(api_key)
        base_url = self._normalize_base_url(base_url)
        prompt = str(prompt or "")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        if api_mode == "chat_completions":
            message_content = [{"type": "text", "text": prompt}]
            if images is not None:
                for i in range(images.shape[0]):
                    message_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{self._tensor_to_base64_png(images[i])}"},
                        }
                    )
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": message_content}],
                "max_completion_tokens": int(max_output_tokens),
            }
            if instructions and instructions.strip():
                payload["messages"].insert(0, {"role": "system", "content": instructions})
            if reasoning_effort != "none":
                payload["reasoning_effort"] = reasoning_effort
            response_json = self._http_json(
                self._build_endpoint(base_url, api_mode),
                api_key,
                payload=payload,
                method="POST",
                verify_ssl=verify_ssl,
            )
            response_id = response_json.get("id", "")
        else:
            payload = {
                "model": model,
                "input": self._build_input_content(prompt, images),
                "max_output_tokens": int(max_output_tokens),
                "store": True,
                "text": {"verbosity": verbosity},
                "reasoning": {"effort": reasoning_effort},
            }
            if instructions and instructions.strip():
                payload["instructions"] = instructions

            response_json = self._http_json(
                self._build_endpoint(base_url, api_mode),
                api_key,
                payload=payload,
                method="POST",
                verify_ssl=verify_ssl,
            )
            response_id = response_json.get("id", "")
            status = response_json.get("status")

            if status not in ("completed", "incomplete"):
                if not response_id:
                    raise ValueError(f"OpenAI API returned no response id: {json.dumps(response_json, ensure_ascii=False)}")
                response_json = self._wait_for_response(
                    api_key, base_url, response_id, poll_interval, max_wait_seconds, verify_ssl
                )

        text = self._extract_text(response_json, api_mode)
        if not text:
            raise ValueError(f"No text output found in OpenAI response: {json.dumps(response_json, ensure_ascii=False)}")
        return (text, response_json.get("id", response_id))

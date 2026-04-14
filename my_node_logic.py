import os
import re
import sys
import json
import uuid
import subprocess
import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import folder_paths

# Windows 下隐藏 cjpegli 弹出的黑框；非 Windows 上此 flag 为 0（no-op）
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


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
    def INPUT_TYPES(s):
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
    CATEGORY = "Wudd Nodes"

    # ---------- helpers ----------

    @staticmethod
    def _image_key_order(key):
        """把 image_1 / image_10 / image_2 按数字排序而不是字典序。"""
        try:
            return int(key.split("_", 1)[1])
        except (ValueError, IndexError):
            return 10 ** 9

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

        # 合并所有图像输入，按数字序排列
        all_images = {"image_1": image_1, **kwargs}
        ordered_keys = sorted(
            (k for k, v in all_images.items()
             if k.startswith("image_") and v is not None),
            key=self._image_key_order,
        )

        # 统计本次调用的图像总数，用于覆盖模式的命名判断
        total_images = sum(len(all_images[k]) for k in ordered_keys)

        png_metadata = (self._build_pnginfo(prompt, extra_pnginfo)
                        if extension == "png" else None)

        # 追加模式：确定本次批次编号（扫描已有文件取最大值 +1）
        if save_mode == "append":
            run = self._find_next_run(full_output_folder, filename, ext)

        results = []
        seq = 0  # 本次调用内的图像序号（1-based）

        for key in ordered_keys:
            images = all_images[key]
            for image in images:
                seq += 1
                i_data = (255.0 * image.cpu().numpy()).clip(0, 255).astype(np.uint8)
                img_pil = Image.fromarray(i_data)

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
    mask 未连接或全为 1（全不透明）时直通。
    背景可选棋盘格或纯色填充。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (["checkerboard", "fill_color"],),
                "fill_color": ("STRING", {"default": "#808080"}),
                "tile_size": ("INT", {"default": 16, "min": 4, "max": 128, "step": 4}),
            },
            "optional": {
                # MASK 形状：[B, H, W]，值 1=不透明，0=透明
                "mask": ("MASK",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "drop_alpha"
    CATEGORY = "Wudd Nodes"

    @staticmethod
    def _parse_hex_color(hex_str: str):
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

    def drop_alpha(self, image, mode, fill_color, tile_size, mask=None):
        import torch

        # mask 未连接 → 直通
        if mask is None:
            return (image,)

        # mask 全为不透明 → 直通
        if mask.min().item() >= 1.0 - 1e-5:
            return (image,)

        # mask: [B, H, W] → [B, H, W, 1] 以便广播
        alpha = mask.unsqueeze(-1).to(image.dtype).to(image.device)

        B, H, W, _ = image.shape

        if mode == "checkerboard":
            board = self._make_checkerboard(H, W, tile_size)          # [H, W, 3]
            bg = torch.from_numpy(board).to(image.device)             # [H, W, 3]
            bg = bg.unsqueeze(0).expand(B, -1, -1, -1)               # [B, H, W, 3]
        else:  # fill_color
            r, g, b = self._parse_hex_color(fill_color)
            bg = torch.tensor([r, g, b], dtype=image.dtype,
                              device=image.device).view(1, 1, 1, 3).expand(B, H, W, -1)

        # alpha 合成：result = image * alpha + bg * (1 - alpha)
        result = (image * alpha + bg * (1.0 - alpha)).clamp(0.0, 1.0)
        return (result,)


class WuddTextSplitter:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "index": ("INT", {"default": 0, "min": 0, "max": 99999}),
                "skip_empty": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "split_text"
    CATEGORY = "Wudd Nodes"

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
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "count": ("INT", {"default": 2, "min": 1, "max": s.MAX_OUTPUTS}),
                "skip_empty": ("BOOLEAN", {"default": False}),
            }
        }

    # 固定声明最大数量；JS 动态隐藏多余的输出槽
    RETURN_TYPES = ("STRING",) * MAX_OUTPUTS
    RETURN_NAMES = tuple(f"line_{i}" for i in range(MAX_OUTPUTS))
    FUNCTION = "split_text"
    CATEGORY = "Wudd Nodes"

    def split_text(self, text, count, skip_empty=False):
        lines = text.splitlines()
        if skip_empty:
            lines = [line for line in lines if line.strip()]
        # 返回恰好 MAX_OUTPUTS 个值；超出 count 的槽只是空字符串，前端不连接即可
        return tuple(lines[i] if i < len(lines) else "" for i in range(self.MAX_OUTPUTS))

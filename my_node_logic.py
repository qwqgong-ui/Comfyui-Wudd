import os
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
        # 启动时检测一次，避免每张图都去碰一次文件系统
        self.cjpegli_available = os.path.isfile(self.cjpegli_exe)
        if not self.cjpegli_available:
            print(f"[Wudd] cjpegli not found at {self.cjpegli_exe}; "
                  f"jpegli mode will fall back to PIL JPEG.")

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image_1": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "Wudd_Img"}),
                "extension": (["png", "jpegli"],),
                "quality": ("INT", {"default": 90, "min": 1, "max": 100}),
                "progressive": ("BOOLEAN", {"default": True}),
                "enable_xyb": ("BOOLEAN", {"default": False}),
                "chroma_subsampling": (["444", "440", "422", "420"],),
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
        # PIL 只认 444/422/420，440 没有对应值——回退到默认即可
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
            # cjpegli 启动失败（权限、路径、跨平台等）——这是原版代码漏掉的分支
            print(f"[Wudd] cjpegli not runnable: {e}")
            self._pil_jpeg_fallback(img_pil, file_path, quality, progressive,
                                    chroma_subsampling, "cjpegli unavailable")
        finally:
            if os.path.exists(temp_png):
                try:
                    os.remove(temp_png)
                except OSError:
                    pass

    # ---------- main entry ----------

    def save_images(self, image_1, filename_prefix="Wudd_Img", extension="png",
                    quality=90, progressive=True, enable_xyb=False,
                    chroma_subsampling="444", prompt=None, extra_pnginfo=None,
                    **kwargs):
        # 传入真实尺寸，保证 %width%/%height% 这类占位符正确
        height, width = image_1.shape[1], image_1.shape[2]
        full_output_folder, filename, counter, subfolder, filename_prefix = \
            folder_paths.get_save_image_path(filename_prefix, self.output_dir,
                                             width, height)

        # 合并后按数字序排序，避免 image_10 排到 image_2 前面
        all_images = {"image_1": image_1, **kwargs}
        ordered_keys = sorted(
            (k for k, v in all_images.items()
             if k.startswith("image_") and v is not None),
            key=self._image_key_order,
        )

        png_metadata = (self._build_pnginfo(prompt, extra_pnginfo)
                        if extension == "png" else None)

        results = []
        for key in ordered_keys:
            images = all_images[key]
            seq_num = key.split("_", 1)[1]

            for batch_num, image in enumerate(images):
                i_data = (255.0 * image.cpu().numpy()).clip(0, 255).astype(np.uint8)
                img_pil = Image.fromarray(i_data)

                ext = "jpg" if extension == "jpegli" else "png"
                file_name = f"{filename}_{counter:05}_seq{seq_num}_b{batch_num}.{ext}"
                file_path = os.path.join(full_output_folder, file_name)

                if extension == "png":
                    img_pil.save(file_path, pnginfo=png_metadata, compress_level=4)
                else:
                    self._save_jpegli(img_pil, file_path, full_output_folder,
                                      quality, progressive, enable_xyb,
                                      chroma_subsampling)

                results.append({
                    "filename": file_name,
                    "subfolder": subfolder,
                    "type": self.type,
                })
                counter += 1

        return {"ui": {"images": results}}


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
        # splitlines 自动处理 \n / \r\n，并剥掉行尾换行
        lines = text.splitlines()

        if skip_empty:
            # 跳过 strip() 后为空的行
            lines = [line for line in lines if line.strip()]

        if 0 <= index < len(lines):
            return (lines[index],)

        return ("",)

"""Core implementation for WuddMultiSaveImage."""
import os
import re
import sys
import json
import uuid
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from PIL.PngImagePlugin import PngInfo
import folder_paths

from .common import (
    CREATE_NO_WINDOW,
    collect_image_inputs,
    tensor_to_pil,
)

class WuddMultiSaveImage:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        exe_name = "cjpegli.exe" if sys.platform == "win32" else "cjpegli"
        package_dir = os.path.dirname(os.path.dirname(__file__))
        cjpegli_candidates = [
            os.path.join(package_dir, "bin", exe_name),
            os.path.join(package_dir, "bin", "jxl-x64-windows-static", "bin", exe_name),
            os.path.join(package_dir, "jxl-x64-windows-static", "bin", exe_name),
            shutil.which(exe_name),
        ]
        self.cjpegli_exe = next(
            (path for path in cjpegli_candidates if path and os.path.isfile(path)),
            cjpegli_candidates[0],
        )
        self.cjpegli_available = os.path.isfile(self.cjpegli_exe)
        if not self.cjpegli_available:
            print(f"[Wudd] cjpegli not found in local bin, bundled tools, or PATH; "
                  f"jpegli mode will fall back to PIL JPEG.")

    # ---------- helpers ----------

    @staticmethod
    def _cache_dir():
        cache_dir = os.path.join(
            folder_paths.get_temp_directory(),
            "image",
            "wudd_save_cache",
        )
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    @staticmethod
    def _safe_cache_stem(name):
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "image")).strip("._")
        return stem or "image"

    @classmethod
    def _backup_path(cls, file_name):
        stem, ext = os.path.splitext(os.path.basename(file_name))
        safe_stem = cls._safe_cache_stem(stem)
        return os.path.join(cls._cache_dir(), f"{safe_stem}_{uuid.uuid4().hex}{ext}")

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
    def _append_file_name(filename, run, seq, ext):
        return f"{filename}.{run:05}.{seq:02}.{ext}"

    @classmethod
    def _append_run_has_collisions(cls, folder, filename, ext, run, total_images):
        for seq in range(1, total_images + 1):
            file_name = cls._append_file_name(filename, run, seq, ext)
            if os.path.exists(os.path.join(folder, file_name)):
                return True
        return False

    @classmethod
    def _plan_saves(cls, folder, filename, subfolder, ext, save_mode, total_images,
                    output_type):
        plans = []
        if save_mode == "append":
            run = cls._find_next_run(folder, filename, ext)
            while cls._append_run_has_collisions(folder, filename, ext, run, total_images):
                run += 1
            for seq in range(1, total_images + 1):
                file_name = cls._append_file_name(filename, run, seq, ext)
                plans.append({
                    "file_name": file_name,
                    "file_path": os.path.join(folder, file_name),
                    "ui": {
                        "filename": file_name,
                        "subfolder": subfolder,
                        "type": output_type,
                    },
                })
            return plans

        for seq in range(1, total_images + 1):
            if total_images == 1:
                file_name = f"{filename}.{ext}"
            else:
                file_name = f"{filename}.{seq:02}.{ext}"
            plans.append({
                "file_name": file_name,
                "file_path": os.path.join(folder, file_name),
                "ui": {
                    "filename": file_name,
                    "subfolder": subfolder,
                    "type": output_type,
                },
            })
        return plans

    @staticmethod
    def _save_worker_count(total_images):
        if total_images <= 1:
            return 1
        configured = os.environ.get("WUDD_SAVE_WORKERS")
        if configured:
            try:
                return max(1, min(total_images, int(configured)))
            except ValueError:
                pass
        return max(1, min(total_images, os.cpu_count() or 1, 4))

    @staticmethod
    def _pnginfo_items(prompt, extra_pnginfo):
        """镜像 ComfyUI 默认 SaveImage 的元数据写入，保证 PNG 能拖回还原工作流。"""
        try:
            from comfy.cli_args import args as comfy_args
            if getattr(comfy_args, "disable_metadata", False):
                return []
        except Exception:
            # 保持旧版 ComfyUI / 独立测试环境中的既有保存行为。
            pass

        items = []
        if prompt is not None:
            items.append(("prompt", json.dumps(prompt)))
        if extra_pnginfo is not None:
            for k, v in extra_pnginfo.items():
                items.append((k, json.dumps(v)))
        return items

    @staticmethod
    def _build_pnginfo_from_items(items):
        metadata = PngInfo()
        for k, v in items:
            metadata.add_text(k, v)
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

    def _do_save(self, img_pil, file_path, extension, png_metadata_items,
                 folder, quality, progressive, enable_xyb, chroma_subsampling):
        if extension == "png":
            png_metadata = self._build_pnginfo_from_items(png_metadata_items or [])
            img_pil.save(file_path, pnginfo=png_metadata, compress_level=4)
        else:
            self._save_jpegli(img_pil, file_path, folder,
                              quality, progressive, enable_xyb, chroma_subsampling)

    def _save_with_backup(self, img_pil, file_path, file_name, extension,
                          png_metadata_items, quality, progressive, enable_xyb,
                          chroma_subsampling):
        backup_path = self._backup_path(file_name)
        backup_folder = os.path.dirname(backup_path)
        backup_stem, backup_ext = os.path.splitext(os.path.basename(backup_path))
        staging_path = os.path.join(
            backup_folder,
            f".{backup_stem}.staging_{uuid.uuid4().hex}{backup_ext}",
        )
        try:
            self._do_save(img_pil, staging_path, extension, png_metadata_items,
                          backup_folder, quality, progressive, enable_xyb,
                          chroma_subsampling)
            os.replace(staging_path, backup_path)
        finally:
            try:
                if os.path.exists(staging_path):
                    os.remove(staging_path)
            except OSError:
                pass

        shutil.copy2(backup_path, file_path)
        return backup_path

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
        images_to_save = [image for images in tensors for image in images]
        total_images = len(images_to_save)

        png_metadata_items = (self._pnginfo_items(prompt, extra_pnginfo)
                              if extension == "png" else None)
        plans = self._plan_saves(full_output_folder, filename, subfolder, ext,
                                 save_mode, total_images, self.type)

        def save_one(job):
            image, plan = job
            img_pil = tensor_to_pil(image)
            self._save_with_backup(img_pil, plan["file_path"], plan["file_name"],
                                   extension, png_metadata_items, quality,
                                   progressive, enable_xyb, chroma_subsampling)

        jobs = list(zip(images_to_save, plans))
        workers = self._save_worker_count(len(jobs))
        if workers <= 1:
            for job in jobs:
                save_one(job)
        else:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="wudd-save") as executor:
                list(executor.map(save_one, jobs))

        results = [plan["ui"] for plan in plans]

        return {"ui": {"images": results}}

__all__ = [
    "WuddMultiSaveImage",
]

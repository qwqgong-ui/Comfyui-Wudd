"""Core implementation for WuddImageListImporter."""
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

class WuddImageListImporter:
    MAX_IMAGES = 50
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif")

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

    @staticmethod
    def _resolve_folder_path(folder_path):
        """允许绝对路径或相对 ComfyUI input/ 的路径；目录不存在返回 None。"""
        folder_path = (folder_path or "").strip().strip('"').strip("'")
        if not folder_path:
            return None
        if not os.path.isabs(folder_path):
            folder_path = os.path.join(folder_paths.get_input_directory(), folder_path)
        return folder_path if os.path.isdir(folder_path) else None

    @staticmethod
    def _folder_sort_key(filename):
        """
        解析 'name.A.B.C.ext' 风格文件名的数字段。
        主键 = 扩展名前的数字（最右），次键向左依次比较。
        例：详情页.00001.01.png → (1, 1)，参与排序时反转为 (1, 1)；
            详情页.00001.10.png → (1, 10)，反转为 (10, 1)；
            排序结果 .01 在 .10 之前。
        非数字段忽略；无任何数字段则按字典序排到最后。
        """
        stem = os.path.splitext(filename)[0]
        nums = tuple(int(p) for p in stem.split(".") if p.isdigit())
        if not nums:
            return (1, filename.lower())
        return (0, tuple(reversed(nums)), filename.lower())

    @classmethod
    def _scan_folder(cls, folder_path):
        """返回按 _folder_sort_key 排序后的图片绝对路径列表。"""
        try:
            entries = [e for e in os.listdir(folder_path)
                       if e.lower().endswith(cls.IMAGE_EXTS)
                       and os.path.isfile(os.path.join(folder_path, e))]
        except OSError:
            return []
        entries.sort(key=cls._folder_sort_key)
        return [os.path.join(folder_path, e) for e in entries]

    @classmethod
    def INPUT_TYPES(cls):
        files = cls._list_input_files()
        inputs = {
            "required": {
                "image_count": ("INT", {"default": 1, "min": 1, "max": cls.MAX_IMAGES, "step": 1}),
                "mode":        (["files", "folder"], {"default": "files"}),
                "folder_path": ("STRING", {"default": "", "multiline": False,
                                            "tooltip": "文件夹路径（绝对或相对 ComfyUI input/）"}),
            },
            "optional": {},
        }
        for i in range(1, cls.MAX_IMAGES + 1):
            inputs["required"][f"image_{i}"] = (files, {"image_upload": True})
        return inputs

    @classmethod
    def IS_CHANGED(cls, image_count, mode="files", folder_path="", **kwargs):
        """缓存键：folder 模式取目录下匹配文件 + mtime；files 模式按所选文件名 + mtime。"""
        if mode == "folder":
            resolved = cls._resolve_folder_path(folder_path)
            parts = ["folder", str(image_count), str(resolved)]
            if resolved:
                for path in cls._scan_folder(resolved)[:image_count]:
                    try:
                        parts.append(f"{os.path.basename(path)}:{os.path.getmtime(path)}")
                    except OSError:
                        pass
            return "|".join(parts)

        parts = ["files", str(image_count)]
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

    @staticmethod
    def _load_image_tensor(image_path):
        """读图 → exif 矫正 → RGB → tensor；失败返回占位空图。"""
        import torch
        from PIL import ImageOps
        try:
            i_img = Image.open(image_path)
            i_img = ImageOps.exif_transpose(i_img)
            return pil_to_tensor(i_img.convert("RGB"))
        except Exception as e:
            print(f"[WuddImageListImporter] Error loading {image_path}: {e}")
            return torch.zeros((1, 64, 64, 3))

    def import_images(self, image_count, mode="files", folder_path="", **kwargs):
        import torch

        if mode == "folder":
            resolved = self._resolve_folder_path(folder_path)
            if resolved is None:
                print(f"[WuddImageListImporter] Folder not found: {folder_path!r}")
                paths = []
            else:
                paths = self._scan_folder(resolved)

            images = []
            for i in range(self.MAX_IMAGES):
                if i >= image_count:
                    images.append(None)
                elif i < len(paths):
                    images.append(self._load_image_tensor(paths[i]))
                else:
                    images.append(torch.zeros((1, 64, 64, 3)))
            return tuple(images)

        # files 模式：按 image_X 选择框逐个加载
        images = []
        for i in range(1, self.MAX_IMAGES + 1):
            if i > image_count:
                images.append(None)
                continue

            image_name = kwargs.get(f"image_{i}")
            if image_name and image_name != "none":
                image_path = folder_paths.get_annotated_filepath(image_name)
                if os.path.exists(image_path):
                    images.append(self._load_image_tensor(image_path))
                else:
                    images.append(torch.zeros((1, 64, 64, 3)))
            else:
                images.append(torch.zeros((1, 64, 64, 3)))

        return tuple(images)

__all__ = [
    "WuddImageListImporter",
]

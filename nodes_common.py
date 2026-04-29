"""
ComfyUI-Wudd — 共享工具与常量。

按功能域拆分的四个模块共用此文件：
    nodes_image.py  图像类节点
    nodes_text.py   文本类节点
    nodes_api.py    外部 API 调用类节点

本文件仅放"真正跨文件复用"的纯函数与常量；节点私有算法仍留在各自类里。
"""

import sys
import base64
import numpy as np
from PIL import Image
from io import BytesIO


# ComfyUI 菜单下的统一分类名；集中声明，重命名只改一处。
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

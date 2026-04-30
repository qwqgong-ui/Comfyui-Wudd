"""
ComfyUI-Wudd — 节点注册入口。

节点按功能域拆分到以下文件：
    nodes_common.py  共享常量与工具
    nodes_image.py   图像类节点（Save / DropAlpha / EdgePad / ListImporter / Stitch）
    nodes_text.py    文本类节点（TextSplitter / MultiTextSplitter / PathJoiner）
    nodes_api.py     外部 API 节点（OpenAIGPT54）
前端动态端口脚本位于 ./web/dynamic_ports.js，由 WEB_DIRECTORY 告知 ComfyUI 加载。
"""

from .nodes_image import (
    WuddMultiSaveImage,
    WuddDropAlpha,
    WuddImageExpand,
    WuddEdgePad,
    WuddImageListImporter,
    WuddImageStitch,
)
from .nodes_text import (
    WuddTextSplitter,
    WuddMultiTextSplitter,
    WuddPathJoiner,
)
from .nodes_api import WuddOpenAIGPT54


NODE_CLASS_MAPPINGS = {
    "WuddMultiSaveImage": WuddMultiSaveImage,
    "WuddTextSplitter": WuddTextSplitter,
    "WuddMultiTextSplitter": WuddMultiTextSplitter,
    "WuddDropAlpha": WuddDropAlpha,
    "WuddImageExpand": WuddImageExpand,
    "WuddEdgePad": WuddEdgePad,
    "WuddImageListImporter": WuddImageListImporter,
    "WuddImageStitch": WuddImageStitch,
    "WuddPathJoiner": WuddPathJoiner,
    "WuddOpenAIGPT54": WuddOpenAIGPT54,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WuddMultiSaveImage": "Wudd Multi Save",
    "WuddTextSplitter": "Wudd Text Splitter",
    "WuddMultiTextSplitter": "Wudd Multi Text Splitter",
    "WuddDropAlpha": "Wudd Drop Alpha",
    "WuddEdgePad": "Wudd Edge Pad",
    "WuddImageListImporter": "Wudd Image List Importer",
    "WuddImageStitch": "Wudd Image Stitch",
    "WuddPathJoiner": "Wudd Path Joiner",
    "WuddOpenAIGPT54": "Wudd OpenAI GPT-5.4",
}

# 告诉 ComfyUI 加载当前目录下的 web 文件夹中的前端脚本
WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']

"""
ComfyUI-Wudd — 节点注册入口。

节点按功能域拆分到以下文件：
    nodes_common.py  共享常量与工具
    nodes_image.py   图像类节点（Save / DropAlpha / EdgePad / ListImporter / Stitch）
    nodes_text.py    文本类节点（TextSplitter / MultiTextSplitter / PathJoiner）
    nodes_audio.py   音频类节点（VideoAudioExtractor / ReplaceVideoAudio）
    nodes_video.py   视频类节点（SaveVideo / FastForwardVideo / ConcatVideos）
    nodes_group.py   画布组控制节点（GroupSwitch）
    nodes_api.py     OpenRouter API 节点（GPT / Claude / Gemini 文本，GPT / Gemini 图像）
前端脚本位于 ./web/，由 WEB_DIRECTORY 告知 ComfyUI 加载。
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
from .nodes_audio import WuddVideoAudioExtractor, WuddReplaceVideoAudio
from .nodes_video import WuddSaveVideo, WuddFastForwardVideo, WuddConcatVideos
from .nodes_group import WuddGroupSwitch
from .nodes_api import (
    WuddOpenRouterGPTText,
    WuddOpenRouterClaudeText,
    WuddOpenRouterGeminiText,
    WuddOpenRouterGPTImage,
    WuddOpenRouterGeminiImage,
)


NODE_CLASS_MAPPINGS = {
    "WuddMultiSaveImage": WuddMultiSaveImage,
    "WuddSaveVideo": WuddSaveVideo,
    "WuddFastForwardVideo": WuddFastForwardVideo,
    "WuddConcatVideos": WuddConcatVideos,
    "WuddTextSplitter": WuddTextSplitter,
    "WuddMultiTextSplitter": WuddMultiTextSplitter,
    "WuddDropAlpha": WuddDropAlpha,
    "WuddImageExpand": WuddImageExpand,
    "WuddEdgePad": WuddEdgePad,
    "WuddImageListImporter": WuddImageListImporter,
    "WuddImageStitch": WuddImageStitch,
    "WuddPathJoiner": WuddPathJoiner,
    "WuddVideoAudioExtractor": WuddVideoAudioExtractor,
    "WuddReplaceVideoAudio": WuddReplaceVideoAudio,
    "WuddOpenRouterGPTText": WuddOpenRouterGPTText,
    "WuddOpenRouterClaudeText": WuddOpenRouterClaudeText,
    "WuddOpenRouterGeminiText": WuddOpenRouterGeminiText,
    "WuddOpenRouterGPTImage": WuddOpenRouterGPTImage,
    "WuddOpenRouterGeminiImage": WuddOpenRouterGeminiImage,
    "WuddGroupSwitch": WuddGroupSwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WuddMultiSaveImage": "Wudd Multi Save",
    "WuddSaveVideo": "Wudd Save Video",
    "WuddFastForwardVideo": "Wudd Video Fast Forward",
    "WuddConcatVideos": "Wudd Concat Videos",
    "WuddTextSplitter": "Wudd Text Splitter",
    "WuddMultiTextSplitter": "Wudd Multi Text Splitter",
    "WuddDropAlpha": "Wudd Drop Alpha",
    "WuddImageExpand": "Wudd Image Expand",
    "WuddEdgePad": "Wudd Edge Pad",
    "WuddImageListImporter": "Wudd Image List Importer",
    "WuddImageStitch": "Wudd Image Stitch",
    "WuddPathJoiner": "Wudd Path Joiner",
    "WuddVideoAudioExtractor": "Wudd Extract Audio From Video",
    "WuddReplaceVideoAudio": "Wudd Replace Video Audio",
    "WuddOpenRouterGPTText": "Wudd OpenRouter GPT Text",
    "WuddOpenRouterClaudeText": "Wudd OpenRouter Claude Text",
    "WuddOpenRouterGeminiText": "Wudd OpenRouter Gemini Text",
    "WuddOpenRouterGPTImage": "Wudd OpenRouter GPT Image",
    "WuddOpenRouterGeminiImage": "Wudd OpenRouter Gemini Image",
    "WuddGroupSwitch": "Wudd Group Switch",
}

# 告诉 ComfyUI 加载当前目录下的 web 文件夹中的前端脚本
WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']

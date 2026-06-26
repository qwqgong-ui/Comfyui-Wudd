"""
ComfyUI-Wudd V1 package entrypoint.

V1 is disabled by default. Use the `wudd_v3` branch / ComfyUI-Wudd-V3 package
for active nodes. Set environment variable `WUDD_ENABLE_V1=1` only when an old
workflow temporarily needs the legacy V1 node ids.
"""

import os


WEB_DIRECTORY = None
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


if os.environ.get("WUDD_ENABLE_V1", "").strip().lower() in {"1", "true", "yes", "on"}:
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
        WuddPromptListFromText,
        WuddPathJoiner,
    )
    from .nodes_audio import WuddVideoAudioExtractor, WuddReplaceVideoAudio
    from .nodes_video import WuddSaveVideo, WuddFastForwardVideo, WuddConcatVideos
    from .nodes_group import WuddGroupSwitch
    from .nodes_browser import WuddChatGPTBrowser
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
        "WuddPromptListFromText": WuddPromptListFromText,
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
        "WuddChatGPTBrowser": WuddChatGPTBrowser,
    }

    NODE_DISPLAY_NAME_MAPPINGS = {
        "WuddMultiSaveImage": "Wudd Multi Save",
        "WuddSaveVideo": "Wudd Save Video",
        "WuddFastForwardVideo": "Wudd Video Fast Forward",
        "WuddConcatVideos": "Wudd Concat Videos",
        "WuddTextSplitter": "Wudd Text Splitter",
        "WuddMultiTextSplitter": "Wudd Multi Text Splitter",
        "WuddPromptListFromText": "Wudd Prompt List From Text",
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
        "WuddChatGPTBrowser": "Wudd ChatGPT Browser",
    }

    WEB_DIRECTORY = "./web"
else:
    print("[Wudd] V1 package is disabled. Use the wudd_v3 branch / ComfyUI-Wudd-V3 package.")


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

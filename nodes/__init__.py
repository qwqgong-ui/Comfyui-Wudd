"""ComfyUI-Wudd-V3 node registration."""

from __future__ import annotations

from comfy_api.latest import IO, ComfyExtension

from .wudd_v3_multi_save_image import WuddV3MultiSaveImage
from .wudd_v3_save_video import WuddV3SaveVideo
from .wudd_v3_fast_forward_video import WuddV3FastForwardVideo
from .wudd_v3_concat_videos import WuddV3ConcatVideos
from .wudd_v3_text_splitter import WuddV3TextSplitter
from .wudd_v3_multi_text_splitter import WuddV3MultiTextSplitter
from .wudd_v3_prompt_list_from_text import WuddV3PromptListFromText
from .wudd_v3_drop_alpha import WuddV3DropAlpha
from .wudd_v3_image_expand import WuddV3ImageExpand
from .wudd_v3_edge_pad import WuddV3EdgePad
from .wudd_v3_image_list_importer import WuddV3ImageListImporter
from .wudd_v3_image_stitch import WuddV3ImageStitch
from .wudd_v3_path_joiner import WuddV3PathJoiner
from .wudd_v3_video_audio_extractor import WuddV3VideoAudioExtractor
from .wudd_v3_replace_video_audio import WuddV3ReplaceVideoAudio
from .wudd_v3_open_router_gpt_text import WuddV3OpenRouterGPTText
from .wudd_v3_open_router_claude_text import WuddV3OpenRouterClaudeText
from .wudd_v3_open_router_gemini_text import WuddV3OpenRouterGeminiText
from .wudd_v3_open_router_gpt_image import WuddV3OpenRouterGPTImage
from .wudd_v3_open_router_gemini_image import WuddV3OpenRouterGeminiImage
from .wudd_v3_group_switch import WuddV3GroupSwitch
from .wudd_v3_chat_gpt_browser import WuddV3ChatGPTBrowser


WUDD_V3_NODE_CLASSES = {
    "WuddV3MultiSaveImage": WuddV3MultiSaveImage,
    "WuddV3SaveVideo": WuddV3SaveVideo,
    "WuddV3FastForwardVideo": WuddV3FastForwardVideo,
    "WuddV3ConcatVideos": WuddV3ConcatVideos,
    "WuddV3TextSplitter": WuddV3TextSplitter,
    "WuddV3MultiTextSplitter": WuddV3MultiTextSplitter,
    "WuddV3PromptListFromText": WuddV3PromptListFromText,
    "WuddV3DropAlpha": WuddV3DropAlpha,
    "WuddV3ImageExpand": WuddV3ImageExpand,
    "WuddV3EdgePad": WuddV3EdgePad,
    "WuddV3ImageListImporter": WuddV3ImageListImporter,
    "WuddV3ImageStitch": WuddV3ImageStitch,
    "WuddV3PathJoiner": WuddV3PathJoiner,
    "WuddV3VideoAudioExtractor": WuddV3VideoAudioExtractor,
    "WuddV3ReplaceVideoAudio": WuddV3ReplaceVideoAudio,
    "WuddV3OpenRouterGPTText": WuddV3OpenRouterGPTText,
    "WuddV3OpenRouterClaudeText": WuddV3OpenRouterClaudeText,
    "WuddV3OpenRouterGeminiText": WuddV3OpenRouterGeminiText,
    "WuddV3OpenRouterGPTImage": WuddV3OpenRouterGPTImage,
    "WuddV3OpenRouterGeminiImage": WuddV3OpenRouterGeminiImage,
    "WuddV3GroupSwitch": WuddV3GroupSwitch,
    "WuddV3ChatGPTBrowser": WuddV3ChatGPTBrowser,
}

NODE_CLASS_MAPPINGS = WUDD_V3_NODE_CLASSES
NODE_DISPLAY_NAME_MAPPINGS = {
    node_id: node_cls.GET_SCHEMA().display_name or node_id
    for node_id, node_cls in WUDD_V3_NODE_CLASSES.items()
}


class WuddV3Extension(ComfyExtension):
    async def get_node_list(self) -> list[type[IO.ComfyNode]]:
        return list(WUDD_V3_NODE_CLASSES.values())


async def comfy_entrypoint() -> WuddV3Extension:
    return WuddV3Extension()


__all__ = [
    "WUDD_V3_NODE_CLASSES",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WuddV3Extension",
    "comfy_entrypoint",
]

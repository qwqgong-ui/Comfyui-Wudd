from .my_node_logic import WuddMultiSaveImage, WuddTextSplitter, WuddMultiTextSplitter

NODE_CLASS_MAPPINGS = {
    "WuddMultiSaveImage": WuddMultiSaveImage,
    "WuddTextSplitter": WuddTextSplitter,
    "WuddMultiTextSplitter": WuddMultiTextSplitter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WuddMultiSaveImage": "Wudd Multi Save",
    "WuddTextSplitter": "Wudd Text Splitter",
    "WuddMultiTextSplitter": "Wudd Multi Text Splitter",
}

# 告诉 ComfyUI 加载当前目录下的 web 文件夹中的前端脚本
WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']

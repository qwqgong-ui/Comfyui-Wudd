"""
V3 adapter layer for ComfyUI-Wudd.

The V3 nodes intentionally keep the V1 implementation classes as the execution
backend.  This keeps image/video/API behavior aligned with the stable V1 package
while exposing a separate set of V3 node ids that can be installed side by side.
"""

from __future__ import annotations

import inspect
from typing import Any

from comfy_api.latest import IO, ComfyExtension

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
from .nodes_api import (
    WuddOpenRouterGPTText,
    WuddOpenRouterClaudeText,
    WuddOpenRouterGeminiText,
    WuddOpenRouterGPTImage,
    WuddOpenRouterGeminiImage,
)


WUDD_V3_CATEGORY = "Wudd Nodes V3"

V1_NODE_CLASSES = {
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
}

V1_DISPLAY_NAMES = {
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
}

_TYPE_MAP = {
    "BOOLEAN": IO.Boolean,
    "INT": IO.Int,
    "FLOAT": IO.Float,
    "STRING": IO.String,
    "IMAGE": IO.Image,
    "MASK": IO.Mask,
    "AUDIO": IO.Audio,
    "VIDEO": IO.Video,
    "*": IO.AnyType,
}

_WIDGET_OPTION_KEYS = {
    "default",
    "min",
    "max",
    "step",
    "round",
    "tooltip",
    "multiline",
    "placeholder",
    "dynamicPrompts",
    "dynamic_prompts",
    "control_after_generate",
    "display",
    "advanced",
    "forceInput",
    "force_input",
    "socketless",
}


def v3_node_id(v1_id: str) -> str:
    if v1_id.startswith("Wudd"):
        return "WuddV3" + v1_id[len("Wudd") :]
    return "WuddV3" + v1_id


def v3_display_name(v1_id: str) -> str:
    display_name = V1_DISPLAY_NAMES.get(v1_id, v1_id)
    if display_name.startswith("Wudd "):
        return "Wudd V3 " + display_name[len("Wudd ") :]
    return "Wudd V3 " + display_name


def v3_category(category: str | None) -> str:
    if not category:
        return WUDD_V3_CATEGORY
    if category.startswith("Wudd Nodes"):
        return WUDD_V3_CATEGORY + category[len("Wudd Nodes") :]
    return category


def _extra_dict(options: dict[str, Any]) -> dict[str, Any] | None:
    extras = {
        key: value
        for key, value in options.items()
        if key not in _WIDGET_OPTION_KEYS
    }
    return extras or None


def _io_for_type(type_name: str):
    return _TYPE_MAP.get(type_name) or IO.Custom(type_name)


def _input_from_v1(name: str, spec: Any, optional: bool):
    if not isinstance(spec, tuple):
        spec = (spec,)
    type_spec = spec[0]
    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    tooltip = options.get("tooltip")
    advanced = options.get("advanced")
    extra_dict = _extra_dict(options)

    if isinstance(type_spec, (list, tuple)):
        default = options.get("default")
        if default is None and type_spec:
            default = type_spec[0]
        return IO.Combo.Input(
            name,
            options=list(type_spec),
            optional=optional,
            default=default,
            tooltip=tooltip,
            control_after_generate=options.get("control_after_generate"),
            extra_dict=extra_dict,
            advanced=advanced,
        )

    if type_spec == "STRING":
        return IO.String.Input(
            name,
            optional=optional,
            default=options.get("default"),
            multiline=options.get("multiline", False),
            placeholder=options.get("placeholder"),
            dynamic_prompts=options.get("dynamic_prompts", options.get("dynamicPrompts")),
            tooltip=tooltip,
            force_input=options.get("force_input", options.get("forceInput")),
            socketless=options.get("socketless"),
            extra_dict=extra_dict,
            advanced=advanced,
        )

    if type_spec == "INT":
        return IO.Int.Input(
            name,
            optional=optional,
            default=options.get("default"),
            min=options.get("min"),
            max=options.get("max"),
            step=options.get("step"),
            control_after_generate=options.get("control_after_generate"),
            tooltip=tooltip,
            force_input=options.get("force_input", options.get("forceInput")),
            socketless=options.get("socketless"),
            extra_dict=extra_dict,
            advanced=advanced,
        )

    if type_spec == "FLOAT":
        return IO.Float.Input(
            name,
            optional=optional,
            default=options.get("default"),
            min=options.get("min"),
            max=options.get("max"),
            step=options.get("step"),
            round=options.get("round"),
            tooltip=tooltip,
            force_input=options.get("force_input", options.get("forceInput")),
            socketless=options.get("socketless"),
            extra_dict=extra_dict,
            advanced=advanced,
        )

    if type_spec == "BOOLEAN":
        return IO.Boolean.Input(
            name,
            optional=optional,
            default=options.get("default"),
            tooltip=tooltip,
            force_input=options.get("force_input", options.get("forceInput")),
            socketless=options.get("socketless"),
            extra_dict=extra_dict,
            advanced=advanced,
        )

    io_type = _io_for_type(str(type_spec))
    return io_type.Input(
        name,
        optional=optional,
        tooltip=tooltip,
        extra_dict=extra_dict,
        advanced=advanced,
    )


def _inputs_from_v1(v1_cls: type) -> tuple[list[Any], list[Any]]:
    input_info = v1_cls.INPUT_TYPES()
    inputs = []
    hidden = []
    for name, spec in input_info.get("required", {}).items():
        inputs.append(_input_from_v1(name, spec, optional=False))
    for name, spec in input_info.get("optional", {}).items():
        inputs.append(_input_from_v1(name, spec, optional=True))
    for hidden_name, hidden_type in input_info.get("hidden", {}).items():
        if hidden_type == "PROMPT":
            hidden.append(IO.Hidden.prompt)
        elif hidden_type == "EXTRA_PNGINFO":
            hidden.append(IO.Hidden.extra_pnginfo)
        elif hidden_type == "UNIQUE_ID":
            hidden.append(IO.Hidden.unique_id)
        else:
            try:
                hidden.append(IO.Hidden[hidden_name])
            except KeyError:
                pass
    return inputs, hidden


def _outputs_from_v1(v1_cls: type) -> list[Any]:
    return_types = tuple(getattr(v1_cls, "RETURN_TYPES", ()) or ())
    return_names = tuple(getattr(v1_cls, "RETURN_NAMES", ()) or ())
    output_is_list = tuple(getattr(v1_cls, "OUTPUT_IS_LIST", ()) or ())
    outputs = []
    for index, type_name in enumerate(return_types):
        io_type = _io_for_type(str(type_name))
        name = return_names[index] if index < len(return_names) else None
        is_list = bool(output_is_list[index]) if index < len(output_is_list) else False
        outputs.append(io_type.Output(id=name, display_name=name, is_output_list=is_list))
    return outputs


class WuddV3Wrapper(IO.ComfyNode):
    V1_CLASS: type | None = None
    V1_NODE_ID: str | None = None
    V3_NODE_ID: str | None = None
    V3_DISPLAY_NAME: str | None = None
    _V1_INSTANCE = None

    @classmethod
    def define_schema(cls):
        v1_cls = cls.V1_CLASS
        inputs, hidden = _inputs_from_v1(v1_cls)
        return IO.Schema(
            node_id=cls.V3_NODE_ID,
            display_name=cls.V3_DISPLAY_NAME,
            category=v3_category(getattr(v1_cls, "CATEGORY", None)),
            inputs=inputs,
            outputs=_outputs_from_v1(v1_cls),
            hidden=hidden,
            is_input_list=bool(getattr(v1_cls, "INPUT_IS_LIST", False)),
            is_output_node=bool(getattr(v1_cls, "OUTPUT_NODE", False)),
            accept_all_inputs=True,
        )

    @classmethod
    def _v1_instance(cls):
        if cls._V1_INSTANCE is None:
            cls._V1_INSTANCE = cls.V1_CLASS()
        return cls._V1_INSTANCE

    @classmethod
    async def execute(cls, **kwargs):
        kwargs = dict(kwargs)
        if bool(getattr(cls.V1_CLASS, "OUTPUT_NODE", False)):
            kwargs.setdefault("prompt", cls.hidden.prompt)
            kwargs.setdefault("extra_pnginfo", cls.hidden.extra_pnginfo)

        function_name = getattr(cls.V1_CLASS, "FUNCTION")
        result = getattr(cls._v1_instance(), function_name)(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        if hasattr(cls.V1_CLASS, "IS_CHANGED"):
            return cls.V1_CLASS.IS_CHANGED(**kwargs)
        return False


def _make_v3_node(v1_id: str, v1_cls: type) -> type[WuddV3Wrapper]:
    node_id = v3_node_id(v1_id)
    return type(
        node_id,
        (WuddV3Wrapper,),
        {
            "V1_CLASS": v1_cls,
            "V1_NODE_ID": v1_id,
            "V3_NODE_ID": node_id,
            "V3_DISPLAY_NAME": v3_display_name(v1_id),
            "__module__": __name__,
        },
    )


WUDD_V3_NODE_CLASSES = {
    v3_node_id(v1_id): _make_v3_node(v1_id, v1_cls)
    for v1_id, v1_cls in V1_NODE_CLASSES.items()
}


class WuddV3Extension(ComfyExtension):
    async def get_node_list(self) -> list[type[IO.ComfyNode]]:
        return list(WUDD_V3_NODE_CLASSES.values())


async def comfy_entrypoint() -> WuddV3Extension:
    return WuddV3Extension()

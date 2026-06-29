"""Core implementation for OpenRouter Gemini image execution."""

from .openrouter_common import *


class WuddOpenRouterGeminiImage(_OpenRouterBase):
    @classmethod
    def INPUT_TYPES(cls):
        optional = _system_and_extra_inputs()
        optional.update(_image_port_inputs(MAX_IMAGE_NODE_INPUTS))
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": ""}),
                "model": (GEMINI_IMAGE_MODELS, {"default": "google/gemini-3.1-flash-image-preview"}),
                "response_modalities": (IMAGE_RESPONSE_MODALITIES, {"default": "IMAGE+TEXT"}),
                "aspect_ratio": (EXTENDED_ASPECT_RATIOS, {"default": "auto"}),
                "image_size": (GEMINI_IMAGE_SIZES, {"default": "auto"}),
                "max_tokens": (
                    "INT",
                    {"default": 4096, "min": 16, "max": 128000, "step": 1},
                ),
                "temperature": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01},
                ),
                "top_p": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "reasoning_effort": (REASONING_EFFORTS, {"default": "none"}),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 2147483647,
                        "step": 1,
                        "control_after_generate": True,
                    },
                ),
                **_api_runtime_inputs(),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "text", "response_id")
    CATEGORY = IMAGE_CATEGORY

    async def generate(
        self,
        prompt,
        api_key,
        model,
        response_modalities,
        aspect_ratio,
        image_size,
        max_tokens,
        temperature,
        top_p,
        reasoning_effort,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        **kwargs,
    ):
        options = {
            "modalities": ["image"] if response_modalities == "IMAGE" else ["image", "text"],
            "max_tokens": int(max_tokens),
        }
        _add_image_config(options, model, aspect_ratio, image_size)
        if float(temperature) != 1.0:
            options["temperature"] = float(temperature)
        if float(top_p) != 1.0:
            options["top_p"] = float(top_p)
        if int(seed) > 0:
            options["seed"] = int(seed)
        _add_reasoning(options, reasoning_effort)

        images = _collect_numbered_images(kwargs, MAX_IMAGE_NODE_INPUTS)
        return await self._image_request(
            prompt,
            api_key,
            model,
            options,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            images=images,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
        )


__all__ = ["WuddOpenRouterGeminiImage"]

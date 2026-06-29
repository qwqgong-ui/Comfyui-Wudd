"""Core implementation for OpenRouter GPT image execution."""

from .openrouter_common import *


class WuddOpenRouterGPTImage(_OpenRouterBase):
    @classmethod
    def INPUT_TYPES(cls):
        optional = _system_and_extra_inputs()
        optional.update(_image_port_inputs(MAX_IMAGE_NODE_INPUTS))
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": ""}),
                "model": (OPENAI_GPT_IMAGE_MODELS, {"default": "openai/gpt-5.4-image-2"}),
                "response_modalities": (IMAGE_RESPONSE_MODALITIES, {"default": "IMAGE+TEXT"}),
                "aspect_ratio": (STANDARD_ASPECT_RATIOS, {"default": "auto"}),
                "image_size": (GPT_IMAGE_SIZES, {"default": "auto"}),
                "max_tokens": (
                    "INT",
                    {"default": 4096, "min": 16, "max": 128000, "step": 1},
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


__all__ = ["WuddOpenRouterGPTImage"]

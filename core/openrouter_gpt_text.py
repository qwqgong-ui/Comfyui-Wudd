"""Core implementation for OpenRouter GPT text execution."""

from .openrouter_common import *


class WuddOpenRouterGPTText(_OpenRouterBase):
    @classmethod
    def INPUT_TYPES(cls):
        optional = _system_and_extra_inputs()
        optional.update(_image_port_inputs(MAX_TEXT_IMAGE_INPUTS))
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": ""}),
                "model": (OPENAI_GPT_TEXT_MODELS, {"default": "openai/gpt-5.5"}),
                "max_tokens": (
                    "INT",
                    {"default": 4096, "min": 16, "max": 128000, "step": 1},
                ),
                "reasoning_effort": (REASONING_EFFORTS, {"default": "none"}),
                "include_reasoning": ("BOOLEAN", {"default": False}),
                "response_format": (TEXT_RESPONSE_FORMATS, {"default": "text"}),
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

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("text", "reasoning", "response_id")
    CATEGORY = TEXT_CATEGORY

    async def generate(
        self,
        prompt,
        api_key,
        model,
        max_tokens,
        reasoning_effort,
        include_reasoning,
        response_format,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        **kwargs,
    ):
        options = {
            "max_tokens": int(max_tokens),
        }
        _add_reasoning(options, reasoning_effort)
        _add_response_format(options, response_format)
        if include_reasoning:
            options["include_reasoning"] = True
        if int(seed) > 0:
            options["seed"] = int(seed)

        images = _collect_numbered_images(kwargs, MAX_TEXT_IMAGE_INPUTS)
        return await self._text_request(
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


__all__ = ["WuddOpenRouterGPTText"]

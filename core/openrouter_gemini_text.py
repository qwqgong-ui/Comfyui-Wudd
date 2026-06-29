"""Core implementation for OpenRouter Gemini text execution."""

from .openrouter_common import *


class WuddOpenRouterGeminiText(_OpenRouterBase):
    @classmethod
    def INPUT_TYPES(cls):
        optional = _system_and_extra_inputs()
        optional.update(_image_port_inputs(MAX_TEXT_IMAGE_INPUTS))
        optional["stop_sequences"] = (
            "STRING",
            {
                "default": "",
                "multiline": True,
                "advanced": True,
            },
        )
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": ""}),
                "model": (GEMINI_TEXT_MODELS, {"default": "google/gemini-3.1-pro-preview"}),
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
        temperature,
        top_p,
        reasoning_effort,
        include_reasoning,
        response_format,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        stop_sequences="",
        **kwargs,
    ):
        options = {
            "max_tokens": int(max_tokens),
        }
        if float(temperature) != 1.0:
            options["temperature"] = float(temperature)
        if float(top_p) != 1.0:
            options["top_p"] = float(top_p)
        if int(seed) > 0:
            options["seed"] = int(seed)
        _add_reasoning(options, reasoning_effort)
        _add_response_format(options, response_format)
        _add_stop_sequences(options, stop_sequences)
        if include_reasoning:
            options["include_reasoning"] = True

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


__all__ = ["WuddOpenRouterGeminiText"]

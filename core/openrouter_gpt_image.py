"""Core implementation for OpenRouter GPT image execution."""

from .openrouter_common import *


class WuddOpenRouterGPTImage(_OpenRouterBase):
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

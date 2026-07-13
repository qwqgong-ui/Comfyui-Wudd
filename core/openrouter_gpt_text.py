"""Core implementation for OpenRouter GPT text execution."""

from .openrouter_common import *


class WuddOpenRouterGPTText(_OpenRouterBase):
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

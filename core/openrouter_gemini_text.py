"""Core implementation for OpenRouter Gemini text execution."""

from .openrouter_common import *


class WuddOpenRouterGeminiText(_OpenRouterBase):
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

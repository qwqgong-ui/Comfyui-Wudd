"""Core implementation for OpenRouter Claude text execution."""

from .openrouter_common import *


class WuddOpenRouterClaudeText(_OpenRouterBase):
    async def generate(
        self,
        prompt,
        api_key,
        model,
        max_tokens,
        temperature,
        top_p,
        top_k,
        verbosity,
        reasoning_effort,
        include_reasoning,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        stop_sequences="",
    ):
        options = {
            "max_tokens": int(max_tokens),
        }
        supports_sampling = "sonnet" in str(model).lower()
        if supports_sampling and float(temperature) != 1.0:
            options["temperature"] = float(temperature)
        if supports_sampling and float(top_p) != 1.0:
            options["top_p"] = float(top_p)
        if supports_sampling and int(top_k) > 0:
            options["top_k"] = int(top_k)
        if verbosity != "none":
            options["verbosity"] = verbosity
        _add_reasoning(options, reasoning_effort)
        _add_stop_sequences(options, stop_sequences)
        if include_reasoning:
            options["include_reasoning"] = True

        return await self._text_request(
            prompt,
            api_key,
            model,
            options,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
        )


__all__ = ["WuddOpenRouterClaudeText"]

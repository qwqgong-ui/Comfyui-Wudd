from __future__ import annotations

from .._base import *


class WuddV3OpenRouterClaudeText(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterClaudeText

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3OpenRouterClaudeText",
            display_name="Wudd V3 OpenRouter Claude Text",
            category=OPENROUTER_TEXT_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input("model", options=CLAUDE_TEXT_MODELS, default="anthropic/claude-sonnet-4.6"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Float.Input("temperature", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Float.Input("top_p", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Int.Input("top_k", default=0, min=0, max=1000, step=1),
                IO.Combo.Input(
                    "verbosity",
                    options=["none", "low", "medium", "high", "xhigh", "max"],
                    default="none",
                ),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                IO.Boolean.Input("include_reasoning", default=False),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                IO.String.Input("stop_sequences", default="", multiline=True, advanced=True),
            ],
            outputs=[
                IO.String.Output("text", display_name="text"),
                IO.String.Output("reasoning", display_name="reasoning"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        ))

    @classmethod
    async def execute(
        cls,
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
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            verbosity=verbosity,
            reasoning_effort=reasoning_effort,
            include_reasoning=include_reasoning,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            stop_sequences=stop_sequences,
        )


__all__ = ["WuddV3OpenRouterClaudeText"]

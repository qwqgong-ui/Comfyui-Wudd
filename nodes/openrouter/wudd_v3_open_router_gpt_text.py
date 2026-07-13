from __future__ import annotations

from .._base import *


class WuddV3OpenRouterGPTText(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterGPTText

    @classmethod
    def define_schema(cls):
        return _with_help(IO.Schema(
            node_id="WuddV3OpenRouterGPTText",
            display_name="Wudd V3 OpenRouter GPT Text",
            category=OPENROUTER_TEXT_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input("model", options=OPENAI_GPT_TEXT_MODELS, default="openai/gpt-5.5"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                IO.Boolean.Input("include_reasoning", default=False),
                IO.Combo.Input("response_format", options=TEXT_RESPONSE_FORMATS, default="text"),
                _seed_input(),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                _image_autogrow(
                    "images",
                    IMAGE_16_NAMES[:MAX_TEXT_IMAGE_INPUTS],
                    min_count=1,
                    optional_items=True,
                ),
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
        reasoning_effort,
        include_reasoning,
        response_format,
        seed,
        base_url,
        timeout_seconds,
        verify_ssl,
        system_prompt="",
        extra_body_json="",
        images=None,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            include_reasoning=include_reasoning,
            response_format=response_format,
            seed=seed,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            **cls._api_image_kwargs(images),
        )


__all__ = ["WuddV3OpenRouterGPTText"]

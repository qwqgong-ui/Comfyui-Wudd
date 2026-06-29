from __future__ import annotations

from ._base import *


class WuddV3OpenRouterGeminiImage(_OpenRouterV3Node, IO.ComfyNode):
    BACKEND_CLS = WuddOpenRouterGeminiImage

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3OpenRouterGeminiImage",
            display_name="Wudd V3 OpenRouter Gemini Image",
            category=OPENROUTER_IMAGE_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.String.Input("api_key", default=""),
                IO.Combo.Input(
                    "model",
                    options=GEMINI_IMAGE_MODELS,
                    default="google/gemini-3.1-flash-image-preview",
                ),
                IO.Combo.Input(
                    "response_modalities",
                    options=IMAGE_RESPONSE_MODALITIES,
                    default="IMAGE+TEXT",
                ),
                IO.Combo.Input("aspect_ratio", options=EXTENDED_ASPECT_RATIOS, default="auto"),
                IO.Combo.Input("image_size", options=GEMINI_IMAGE_SIZES, default="auto"),
                IO.Int.Input("max_tokens", default=4096, min=16, max=128000, step=1),
                IO.Float.Input("temperature", default=1.0, min=0.0, max=2.0, step=0.01),
                IO.Float.Input("top_p", default=1.0, min=0.0, max=1.0, step=0.01),
                IO.Combo.Input("reasoning_effort", options=REASONING_EFFORTS, default="none"),
                _seed_input(),
                *_api_runtime_inputs(),
                *_system_and_extra_inputs(),
                _image_autogrow(
                    "images",
                    IMAGE_16_NAMES[:MAX_IMAGE_NODE_INPUTS],
                    min_count=1,
                    optional_items=True,
                ),
            ],
            outputs=[
                IO.Image.Output("image", display_name="image"),
                IO.String.Output("text", display_name="text"),
                IO.String.Output("response_id", display_name="response_id"),
            ],
        )

    @classmethod
    async def execute(
        cls,
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
        images=None,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "generate",
            prompt=prompt,
            api_key=api_key,
            model=model,
            response_modalities=response_modalities,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            seed=seed,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            system_prompt=system_prompt,
            extra_body_json=extra_body_json,
            **cls._api_image_kwargs(images),
        )


__all__ = ["WuddV3OpenRouterGeminiImage"]

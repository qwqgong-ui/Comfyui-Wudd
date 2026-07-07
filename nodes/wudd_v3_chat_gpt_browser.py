from __future__ import annotations

from ._base import *


class WuddV3ChatGPTBrowser(_FingerprintBackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddChatGPTBrowser

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3ChatGPTBrowser",
            display_name="Wudd V3 ChatGPT Browser",
            category=CHATGPT_BROWSER_CATEGORY,
            inputs=[
                IO.String.Input("prompt", default="", multiline=True),
                IO.Combo.Input(
                    "connection_mode",
                    options=BROWSER_CONNECTION_MODES,
                    default="connect_or_launch_edge",
                ),
                IO.String.Input("cdp_url", default=DEFAULT_CDP_URL, advanced=True),
                IO.Int.Input(
                    "wait_timeout_seconds",
                    default=300,
                    min=10,
                    max=3600,
                    step=1,
                    advanced=True,
                ),
                IO.Float.Input(
                    "stable_seconds",
                    default=2.0,
                    min=0.5,
                    max=30.0,
                    step=0.5,
                    advanced=True,
                ),
                IO.Float.Input(
                    "upload_wait_seconds",
                    default=4.0,
                    min=0.0,
                    max=120.0,
                    step=0.5,
                    advanced=True,
                ),
                IO.Boolean.Input("new_chat", default=True),
                IO.Combo.Input("submit_action", options=SUBMIT_ACTIONS, default="press_enter"),
                IO.Boolean.Input("keep_browser_open", default=True, advanced=True),
                IO.Boolean.Input("background_browser", default=True, advanced=True),
                IO.Int.Input(
                    "parallel_pages",
                    default=2,
                    min=1,
                    max=8,
                    step=1,
                    advanced=True,
                ),
                IO.Int.Input(
                    "run_id",
                    default=0,
                    min=0,
                    max=2147483647,
                    step=1,
                    control_after_generate=True,
                ),
                _image_autogrow("images", IMAGE_16_NAMES, min_count=1, optional_items=True),
                IO.String.Input("browser_executable", default="", advanced=True),
                IO.Boolean.Input("close_page_after_run", default=True, advanced=True),
                IO.Int.Input(
                    "image_error_retries",
                    default=2,
                    min=0,
                    max=10,
                    step=1,
                    advanced=True,
                ),
            ],
            outputs=[
                IO.String.Output("text", display_name="text"),
                IO.String.Output("conversation_url", display_name="conversation_url"),
                IO.Image.Output("images", display_name="images"),
                IO.Int.Output("image_count", display_name="image_count"),
            ],
            hidden=[IO.Hidden.unique_id],
        )

    @classmethod
    async def execute(
        cls,
        prompt,
        connection_mode,
        cdp_url,
        wait_timeout_seconds,
        stable_seconds,
        upload_wait_seconds,
        new_chat,
        submit_action,
        keep_browser_open,
        background_browser,
        parallel_pages,
        run_id,
        images: IO.Autogrow.Type | None = None,
        browser_executable="",
        close_page_after_run=True,
        image_error_retries=2,
    ) -> IO.NodeOutput:
        return await cls._run_backend(
            "submit",
            prompt=prompt,
            connection_mode=connection_mode,
            cdp_url=cdp_url,
            wait_timeout_seconds=wait_timeout_seconds,
            stable_seconds=stable_seconds,
            upload_wait_seconds=upload_wait_seconds,
            new_chat=new_chat,
            submit_action=submit_action,
            keep_browser_open=keep_browser_open,
            close_page_after_run=close_page_after_run,
            background_browser=background_browser,
            parallel_pages=parallel_pages,
            run_id=run_id,
            images=_numbered_kwargs(images, "image_"),
            browser_executable=browser_executable,
            image_error_retries=image_error_retries,
            unique_id=cls.hidden.unique_id,
        )

__all__ = ["WuddV3ChatGPTBrowser"]

"""Wudd ChatGPT browser backend entrypoint."""

from .browser_5_pages import *

class WuddChatGPTBrowser:
    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return _stable_hash(cls.__name__, args, kwargs)

    async def submit(
        self,
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
        image=None,
        images=None,
        browser_executable="",
        close_page_after_run=True,
        image_error_retries=2,
        user_data_dir=DEFAULT_BROWSER_USER_DATA_DIR,
        unique_id=None,
        **image_kwargs,
    ):
        prompt = str(prompt or "")
        input_frames = _input_image_frames(image=image, images=images, extra_images=image_kwargs)
        if not prompt.strip() and not input_frames:
            raise ValueError("Prompt or image is required.")
        if connection_mode not in BROWSER_CONNECTION_MODES:
            raise ValueError(f"Unsupported connection_mode: {connection_mode}")
        if submit_action not in SUBMIT_ACTIONS:
            raise ValueError(f"Unsupported submit_action: {submit_action}")
        parallel_pages = _normalize_parallel_pages(parallel_pages)
        try:
            image_error_retries = int(image_error_retries)
        except (TypeError, ValueError):
            image_error_retries = 2
        image_error_retries = max(0, min(10, image_error_retries))

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ImportError(
                "Wudd ChatGPT Browser requires Playwright. Install it in the ComfyUI "
                "Python environment with: python -m pip install playwright"
            ) from exc

        chatgpt_url = DEFAULT_CHATGPT_URL
        cdp_base, _, _ = _normalize_cdp_url(cdp_url)
        upload_paths = []
        browser_session = None
        page = None
        page_id = None
        image_collector = None
        run_owner = None
        close_page_after_run = bool(close_page_after_run) or not bool(keep_browser_open)
        _check_interrupted()

        try:
            run_owner = await _acquire_chatgpt_run_slot(unique_id)
            browser_session = await _get_browser_session(
                async_playwright,
                connection_mode,
                cdp_base,
                browser_executable,
                user_data_dir,
                background_browser=bool(background_browser),
            )
            page, page_id = await _get_chatgpt_page(
                browser_session,
                chatgpt_url,
                bool(new_chat),
                parallel_pages,
                bool(background_browser),
            )
            await _dismiss_frequent_request_notice(page)
            ignored_image_fingerprints = set()
            if input_frames:
                for frame in input_frames:
                    ignored_image_fingerprints.add(_image_fingerprint(tensor_to_pil(frame).convert("RGB")))

            last_generation_error = ""
            for attempt_index in range(image_error_retries + 1):
                _check_interrupted()
                await _dismiss_frequent_request_notice(page)
                previous_count = len(await _assistant_texts(page))
                composer = await _first_visible_locator(page, COMPOSER_SELECTORS, wait_timeout_seconds)

                if input_frames:
                    attempt_upload_paths = _make_upload_pngs(input_frames)
                    upload_paths.extend(attempt_upload_paths)
                    await _attach_image_file(page, attempt_upload_paths, wait_timeout_seconds)
                    if float(upload_wait_seconds) > 0:
                        await _sleep_interruptible(float(upload_wait_seconds))
                    composer = await _first_visible_locator(page, COMPOSER_SELECTORS, wait_timeout_seconds)

                if image_collector is not None:
                    image_collector.stop()
                    image_collector = None
                ignored_image_urls = await _page_known_image_urls(page)
                image_collector = _ImageResponseCollector(
                    page,
                    ignored_urls=ignored_image_urls,
                    ignored_fingerprints=ignored_image_fingerprints,
                )
                image_collector.start()

                composer = await _first_visible_locator(page, COMPOSER_SELECTORS, wait_timeout_seconds)
                await _fill_composer(composer, page, prompt, wait_timeout_seconds)
                await _submit_chatgpt_composer(page, composer, submit_action, previous_count, wait_timeout_seconds)

                if background_browser:
                    await _minimize_browser_window(page)

                text, images = await _wait_for_response_result(
                    page,
                    image_collector,
                    previous_count,
                    wait_timeout_seconds,
                    stable_seconds,
                    prompt,
                )
                if images or not _image_generation_failed_text(text):
                    return (text, page.url, _pil_images_to_tensor_batch(images), len(images))

                last_generation_error = text
                if attempt_index >= image_error_retries:
                    break
                await _sleep_interruptible(1.0)

            raise RuntimeError(
                "ChatGPT image generation failed after "
                f"{image_error_retries + 1} attempt(s): {last_generation_error}"
            )
        except BaseException:
            if page is not None:
                await _try_stop_response(page)
                await _close_page_quietly(page)
            raise
        finally:
            if image_collector is not None:
                image_collector.stop()
            if page_id is not None:
                if page is not None and close_page_after_run:
                    await _close_page_quietly(page)
                await _release_chatgpt_page_slot(browser_session, page_id)

            for upload_path in upload_paths:
                if upload_path and os.path.exists(upload_path):
                    try:
                        os.remove(upload_path)
                    except OSError:
                        pass

            try:
                await _maybe_close_spawned_browser_session(browser_session, keep_browser_open)
            finally:
                if run_owner is not None:
                    await _release_chatgpt_run_slot(run_owner)

__all__ = ["WuddChatGPTBrowser"]

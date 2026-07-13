"""ChatGPT composer, retry, and response-wait helpers."""

from .browser_3_images import *

async def _first_visible_locator(page, selectors, timeout_seconds):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    started_at = time.monotonic()
    primary_selectors = [
        selector for selector in selectors
        if not str(selector).lstrip().lower().startswith("textarea")
    ]
    fallback_selectors = [
        selector for selector in selectors
        if str(selector).lstrip().lower().startswith("textarea")
    ]
    last_error = None
    while time.monotonic() < deadline:
        _check_interrupted()
        await _dismiss_frequent_request_notice(page)
        elapsed = time.monotonic() - started_at
        active_selectors = list(primary_selectors)
        if elapsed >= min(8.0, max(1.0, float(timeout_seconds) * 0.1)):
            active_selectors.extend(fallback_selectors)

        for selector in active_selectors:
            try:
                locator = page.locator(selector)
                count = await _await_interruptible(locator.count())
                for index in range(count - 1, -1, -1):
                    candidate = locator.nth(index)
                    state = await _composer_state(candidate)
                    if bool(state.get("ready")):
                        return candidate
            except Exception as exc:
                last_error = exc
        await _sleep_interruptible(0.4)
    if last_error:
        raise TimeoutError(f"Timed out finding ChatGPT composer: {last_error}") from last_error
    raise TimeoutError("Timed out finding ChatGPT composer. Log in to ChatGPT in the opened browser.")

async def _wait_for_response_images(
    page,
    collector,
    timeout_seconds,
    max_wait_seconds=None,
    stop_when_idle=True,
):
    if max_wait_seconds is None:
        max_wait = min(30.0, max(5.0, float(timeout_seconds) * 0.1))
    else:
        max_wait = max(1.0, min(float(timeout_seconds), float(max_wait_seconds)))
    deadline = time.monotonic() + max_wait
    not_streaming_since = None

    while True:
        _check_interrupted()
        await _dismiss_frequent_request_notice(page)
        images = await _collect_response_images(page, collector, min(5.0, float(timeout_seconds)))
        if images:
            return images

        now = time.monotonic()
        if now >= deadline:
            break

        if stop_when_idle:
            if await _is_streaming(page):
                not_streaming_since = None
            else:
                if not_streaming_since is None:
                    not_streaming_since = now
                elif now - not_streaming_since >= 5.0:
                    break

        await _sleep_interruptible(0.75)

    if collector is not None:
        images = await collector.drain(2.0)
        return _dedupe_images(images, ignored_fingerprints=collector.ignored_fingerprints)
    return []


async def _is_streaming(page):
    try:
        return bool(await _page_evaluate_with_navigation_retry(page, STREAMING_SCRIPT, attempts=2))
    except Exception:
        return False


async def _try_stop_response(page):
    try:
        await asyncio.wait_for(
            _page_evaluate_with_navigation_retry(page, STOP_RESPONSE_SCRIPT, attempts=1),
            timeout=3.0,
        )
    except Exception:
        pass


async def _dismiss_frequent_request_notice(page):
    if page is None or _page_is_closed(page):
        return False
    try:
        return bool(await asyncio.wait_for(
            _page_evaluate_with_navigation_retry(
                page,
                DISMISS_FREQUENT_REQUEST_NOTICE_SCRIPT,
                attempts=1,
            ),
            timeout=3.0,
        ))
    except Exception:
        return False


async def _click_chatgpt_retry_button(page):
    if page is None or _page_is_closed(page):
        return False
    try:
        return bool(await asyncio.wait_for(
            _page_evaluate_with_navigation_retry(
                page,
                CLICK_CHATGPT_RETRY_BUTTON_SCRIPT,
                attempts=1,
            ),
            timeout=3.0,
        ))
    except Exception:
        return False


async def _refresh_chatgpt_page_quietly(page, timeout_seconds=30.0):
    if page is None or _page_is_closed(page):
        return False
    refresh_timeout = max(5000, int(min(30.0, max(1.0, float(timeout_seconds))) * 1000))
    try:
        await _await_interruptible(
            page.reload(wait_until="domcontentloaded", timeout=refresh_timeout),
            interval=0.25,
        )
    except Exception:
        if page is None or _page_is_closed(page):
            return False
    await _wait_for_page_navigation_settled(page, min(10.0, max(1.0, float(timeout_seconds))))
    await _dismiss_frequent_request_notice(page)
    return not _page_is_closed(page)


def _normalize_composer_text(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


async def _composer_state(composer):
    try:
        state = await _await_interruptible(composer.evaluate(COMPOSER_STATE_SCRIPT))
    except Exception:
        return {"ready": False, "text": ""}
    if not isinstance(state, dict):
        return {"ready": False, "text": ""}
    return state


async def _wait_for_composer_ready(composer, timeout_seconds):
    deadline = time.monotonic() + max(5.0, min(60.0, float(timeout_seconds)))
    ready_since = None
    last_state = {"ready": False, "text": ""}

    while time.monotonic() < deadline:
        _check_interrupted()
        last_state = await _composer_state(composer)
        if bool(last_state.get("ready")):
            if ready_since is None:
                ready_since = time.monotonic()
            elif time.monotonic() - ready_since >= 0.5:
                return last_state
        else:
            ready_since = None
        await _sleep_interruptible(0.2)

    raise TimeoutError(f"ChatGPT composer did not become ready: {last_state}")


async def _attach_image_file(page, file_paths, timeout_seconds):
    if isinstance(file_paths, (list, tuple)):
        upload_files = [str(path) for path in file_paths if path]
    else:
        upload_files = [str(file_paths)] if file_paths else []
    if not upload_files:
        return

    timeout_ms = max(1000, int(float(timeout_seconds) * 1000))
    file_inputs = page.locator('input[type="file"]')
    try:
        if await _await_interruptible(file_inputs.count()) > 0:
            await _await_interruptible(
                file_inputs.first.set_input_files(upload_files, timeout=timeout_ms),
            )
            return
    except Exception:
        pass

    for selector in ATTACH_BUTTON_SELECTORS:
        button = page.locator(selector).last
        try:
            if (
                await _await_interruptible(button.count()) == 0 or
                not await _await_interruptible(button.is_visible())
            ):
                continue
            async with page.expect_file_chooser(timeout=timeout_ms) as file_chooser_info:
                await _await_interruptible(button.click(timeout=timeout_ms))
            file_chooser = await _await_interruptible(file_chooser_info.value)
            await _await_interruptible(file_chooser.set_files(upload_files))
            return
        except Exception:
            try:
                if await _await_interruptible(file_inputs.count()) > 0:
                    await _await_interruptible(
                        file_inputs.first.set_input_files(upload_files, timeout=timeout_ms),
                    )
                    return
            except Exception:
                pass

    raise RuntimeError("Could not find ChatGPT's file upload control.")


async def _fill_composer(composer, page, prompt, timeout_seconds):
    prompt = str(prompt or "")
    expected = _normalize_composer_text(prompt)
    last_text = ""
    modifier = "Meta" if sys.platform == "darwin" else "Control"

    for _ in range(3):
        await _dismiss_frequent_request_notice(page)
        await _wait_for_composer_ready(composer, timeout_seconds)
        await _await_interruptible(composer.click())
        try:
            await _await_interruptible(page.keyboard.press(f"{modifier}+A"))
            await _await_interruptible(page.keyboard.press("Backspace"))
            if prompt:
                await _await_interruptible(page.keyboard.insert_text(prompt))
            actual = None
        except Exception:
            actual = await _await_interruptible(
                composer.evaluate(SET_COMPOSER_TEXT_SCRIPT, prompt),
            )

        await _sleep_interruptible(0.4)
        state = await _composer_state(composer)
        last_text = _normalize_composer_text(state.get("text") if state else actual)
        if last_text == expected:
            return

    raise RuntimeError(
        "ChatGPT composer text verification failed before submit. "
        f"Expected {len(expected)} chars, got {len(last_text)} chars."
    )


async def _click_send_button(page, timeout_seconds, required=True):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        _check_interrupted()
        await _dismiss_frequent_request_notice(page)
        for selector in SEND_BUTTON_SELECTORS:
            try:
                button = page.locator(selector).last
                if await _await_interruptible(button.count()) == 0:
                    continue
                if (
                    await _await_interruptible(button.is_visible()) and
                    await _await_interruptible(button.is_enabled())
                ):
                    await _await_interruptible(button.click())
                    return True
            except Exception:
                pass
        await _sleep_interruptible(0.25)
    if required:
        raise TimeoutError("Timed out finding an enabled ChatGPT send button.")
    return False


async def _response_started(page, previous_count):
    texts = await _assistant_texts(page)
    return len(texts) > previous_count or await _is_streaming(page)


async def _submit_chatgpt_composer(page, composer, submit_action, previous_count, wait_timeout_seconds):
    if submit_action == "click_send_button":
        await _click_send_button(page, wait_timeout_seconds)
        return

    await _await_interruptible(composer.press("Enter"))
    await _sleep_interruptible(2.0)
    frequent_notice_dismissed = await _dismiss_frequent_request_notice(page)
    if not frequent_notice_dismissed and not await _response_started(page, previous_count):
        await _click_send_button(page, min(30.0, float(wait_timeout_seconds)), required=True)


async def _wait_for_response(page, previous_count, timeout_seconds, stable_seconds):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    stable_seconds = max(0.5, float(stable_seconds))
    last_text = ""
    last_change = time.monotonic()
    last_retry_click = 0.0
    last_tab_refresh = time.monotonic()
    ignored_retry_text = ""
    started = False

    while time.monotonic() < deadline:
        _check_interrupted()
        await _dismiss_frequent_request_notice(page)
        texts = await _assistant_texts(page)
        current = ""
        if len(texts) > previous_count:
            started = True
            current = texts[-1]
        elif started and texts:
            current = texts[-1]

        now = time.monotonic()
        if started and now - last_retry_click >= CHATGPT_RETRY_CLICK_COOLDOWN_SECONDS:
            if await _click_chatgpt_retry_button(page):
                last_retry_click = time.monotonic()
                last_tab_refresh = last_retry_click
                ignored_retry_text = current or last_text
                last_text = ""
                last_change = last_retry_click
                await _sleep_interruptible(1.0)
                continue

        if ignored_retry_text and current == ignored_retry_text:
            current = ""
        elif ignored_retry_text and current:
            ignored_retry_text = ""

        if current and current != last_text:
            last_text = current
            last_change = time.monotonic()

        streaming = await _is_streaming(page)
        if last_text and started and not streaming and time.monotonic() - last_change >= stable_seconds:
            return last_text

        now = time.monotonic()
        if (
            now - last_tab_refresh >= CHATGPT_TAB_REFRESH_SECONDS and
            deadline - now > 5.0
        ):
            await _refresh_chatgpt_page_quietly(page, min(30.0, float(timeout_seconds)))
            last_tab_refresh = time.monotonic()
            last_change = last_tab_refresh

        await _sleep_interruptible(0.5)

    if last_text:
        return last_text
    raise TimeoutError("Timed out waiting for ChatGPT response text.")


async def _wait_for_response_result(page, collector, previous_count, timeout_seconds, stable_seconds, prompt):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    stable_seconds = max(0.5, float(stable_seconds))
    image_expected = _prompt_likely_requests_image(prompt)
    last_text = ""
    last_change = time.monotonic()
    last_retry_click = 0.0
    last_tab_refresh = time.monotonic()
    ignored_retry_text = ""
    started = False
    text_ready = False

    while time.monotonic() < deadline:
        _check_interrupted()
        await _dismiss_frequent_request_notice(page)
        images = await _collect_response_images(page, collector, min(3.0, float(timeout_seconds)))
        if images:
            return last_text, images

        texts = await _assistant_texts(page)
        current = ""
        if len(texts) > previous_count:
            started = True
            current = texts[-1]
        elif started and texts:
            current = texts[-1]

        now = time.monotonic()
        if started and now - last_retry_click >= CHATGPT_RETRY_CLICK_COOLDOWN_SECONDS:
            if await _click_chatgpt_retry_button(page):
                last_retry_click = time.monotonic()
                last_tab_refresh = last_retry_click
                ignored_retry_text = current or last_text
                last_text = ""
                last_change = last_retry_click
                text_ready = False
                await _sleep_interruptible(1.0)
                continue

        if ignored_retry_text and current == ignored_retry_text:
            current = ""
        elif ignored_retry_text and current:
            ignored_retry_text = ""

        if current and current != last_text:
            last_text = current
            last_change = time.monotonic()
            text_ready = False

        streaming = await _is_streaming(page)
        if last_text and started and not streaming and time.monotonic() - last_change >= stable_seconds:
            if _image_generation_failed_text(last_text):
                return last_text, []
            if not image_expected:
                images = await _wait_for_response_images(
                    page,
                    collector,
                    timeout_seconds,
                    max_wait_seconds=5.0,
                    stop_when_idle=True,
                )
                return last_text, images
            text_ready = True

        now = time.monotonic()
        if (
            now - last_tab_refresh >= CHATGPT_TAB_REFRESH_SECONDS and
            deadline - now > 5.0
        ):
            await _refresh_chatgpt_page_quietly(page, min(30.0, float(timeout_seconds)))
            last_tab_refresh = time.monotonic()
            last_change = last_tab_refresh
            text_ready = False

        await _sleep_interruptible(0.5 if not text_ready else 1.0)

    images = await _collect_response_images(page, collector, min(5.0, float(timeout_seconds)))
    if images or last_text:
        return last_text, images
    raise TimeoutError("Timed out waiting for ChatGPT response text or image.")


async def _goto_chatgpt(page, chatgpt_url):
    last_error = None
    for wait_until in ("domcontentloaded", "commit"):
        try:
            _check_interrupted()
            await _await_interruptible(
                page.goto(chatgpt_url, wait_until=wait_until, timeout=30000),
                interval=0.25,
            )
            return
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if "ERR_ABORTED" in message and _is_chatgpt_page_url(page.url):
                return
            await _sleep_interruptible(0.75)
    if last_error is not None:
        raise last_error

__all__ = [name for name in globals() if not name.startswith("__")]

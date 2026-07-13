"""Browser page pooling and reusable session helpers."""

from .browser_4_response import *

def _is_reusable_unnamed_chatgpt_page(url, chatgpt_url):
    if not _is_chatgpt_page_url(url):
        return False
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    path = (parsed.path or "/").rstrip("/")
    return path in ("", "/")

def _is_reusable_blank_page(url):
    return str(url or "").strip().lower() in ("", "about:blank")

def _prune_session_page_pool(session):
    if session is None:
        return
    session.page_pool = [
        page for page in session.page_pool
        if not _page_is_closed(page)
    ]
    valid_page_ids = {id(page) for page in session.page_pool}
    session.leased_page_ids.intersection_update(valid_page_ids)

def _claim_reusable_chatgpt_page(session, chatgpt_url):
    pooled_ids = {id(page) for page in session.page_pool}
    for page in reversed(list(session.context.pages)):
        if _page_is_closed(page) or id(page) in pooled_ids:
            continue
        if _is_reusable_blank_page(page.url) or _is_reusable_unnamed_chatgpt_page(page.url, chatgpt_url):
            session.page_pool.append(page)
            return page
    return None

async def _acquire_chatgpt_page(session, chatgpt_url, new_chat, parallel_pages):
    max_pages = _normalize_parallel_pages(parallel_pages)
    lock = _browser_page_pool_lock()

    while True:
        _check_interrupted()
        await _lock_acquire_interruptible(lock)
        try:
            _prune_session_page_pool(session)

            if len(session.leased_page_ids) < max_pages:
                for page in session.page_pool:
                    page_id = id(page)
                    if page_id not in session.leased_page_ids:
                        session.leased_page_ids.add(page_id)
                        return page, page_id

                if len(session.page_pool) < max_pages:
                    page = _claim_reusable_chatgpt_page(session, chatgpt_url)
                    if page is None:
                        page = await _await_interruptible(session.context.new_page())
                        session.page_pool.append(page)
                    page_id = id(page)
                    session.leased_page_ids.add(page_id)
                    return page, page_id
        finally:
            lock.release()

        await _sleep_interruptible(0.25)

async def _release_chatgpt_page_slot(session, page_id):
    if session is None or page_id is None:
        return
    lock = _browser_page_pool_lock()
    await _lock_acquire_interruptible(lock)
    try:
        session.leased_page_ids.discard(page_id)
        _prune_session_page_pool(session)
    finally:
        lock.release()

async def _close_page_quietly(page):
    if page is None or _page_is_closed(page):
        return
    with contextlib.suppress(Exception):
        await asyncio.wait_for(page.close(), timeout=3.0)

async def _minimize_browser_window(page):
    if page is None or _page_is_closed(page):
        return
    cdp_session = None
    try:
        cdp_session = await _await_interruptible(page.context.new_cdp_session(page))
        window_info = await _await_interruptible(cdp_session.send("Browser.getWindowForTarget"))
        window_id = window_info.get("windowId")
        if window_id is not None:
            await _await_interruptible(
                cdp_session.send(
                    "Browser.setWindowBounds",
                    {"windowId": window_id, "bounds": {"windowState": "minimized"}},
                )
            )
    except Exception:
        return
    finally:
        if cdp_session is not None:
            with contextlib.suppress(Exception):
                await cdp_session.detach()

async def _minimize_browser_context_windows(context):
    if context is None:
        return
    seen_window_ids = set()
    for page in list(getattr(context, "pages", []) or []):
        if page is None or _page_is_closed(page):
            continue
        cdp_session = None
        try:
            cdp_session = await _await_interruptible(page.context.new_cdp_session(page))
            window_info = await _await_interruptible(cdp_session.send("Browser.getWindowForTarget"))
            window_id = window_info.get("windowId")
            if window_id is None or window_id in seen_window_ids:
                continue
            seen_window_ids.add(window_id)
            await _await_interruptible(
                cdp_session.send(
                    "Browser.setWindowBounds",
                    {"windowId": window_id, "bounds": {"windowState": "minimized"}},
                )
            )
        except Exception:
            continue
        finally:
            if cdp_session is not None:
                with contextlib.suppress(Exception):
                    await cdp_session.detach()

async def _get_chatgpt_page(session, chatgpt_url, new_chat, parallel_pages, background_browser):
    page, page_id = await _acquire_chatgpt_page(session, chatgpt_url, new_chat, parallel_pages)
    try:
        if background_browser:
            await _minimize_browser_window(page)
        if new_chat or not _is_chatgpt_page_url(page.url):
            await _goto_chatgpt(page, chatgpt_url)
            if background_browser:
                await _minimize_browser_window(page)
        return page, page_id
    except BaseException:
        await _close_page_quietly(page)
        await _release_chatgpt_page_slot(session, page_id)
        raise

async def _connect_browser(
    playwright,
    connection_mode,
    cdp_url,
    browser_executable,
    user_data_dir,
    background_browser=False,
):
    cdp_base, _, _ = _normalize_cdp_url(cdp_url)
    spawned = None

    if connection_mode == "connect_or_launch_chrome":
        if not _is_cdp_ready(cdp_base):
            spawned = await _launch_browser_and_wait(
                "chrome",
                cdp_base,
                browser_executable,
                user_data_dir,
                background_browser=background_browser,
            )
    elif connection_mode == "connect_or_launch_edge":
        if not _is_cdp_ready(cdp_base):
            spawned = await _launch_browser_and_wait(
                "edge",
                cdp_base,
                browser_executable,
                user_data_dir,
                background_browser=background_browser,
            )
    elif connection_mode == "launch_chrome":
        spawned = await _launch_browser_and_wait(
            "chrome",
            cdp_base,
            browser_executable,
            user_data_dir,
            background_browser=background_browser,
        )
    elif connection_mode == "launch_edge":
        spawned = await _launch_browser_and_wait(
            "edge",
            cdp_base,
            browser_executable,
            user_data_dir,
            background_browser=background_browser,
        )

    _check_interrupted()
    browser = await _await_interruptible(playwright.chromium.connect_over_cdp(cdp_base))
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    if background_browser and spawned is not None:
        await _minimize_browser_context_windows(context)
    return browser, context, spawned

async def _get_browser_session(
    async_playwright_factory,
    connection_mode,
    cdp_url,
    browser_executable,
    user_data_dir,
    background_browser=False,
):
    cdp_base, _, _ = _normalize_cdp_url(cdp_url)
    session_key = _browser_session_key(cdp_base)

    lock = _browser_execution_lock()
    await _lock_acquire_interruptible(lock)
    try:
        session = _BROWSER_SESSIONS.get(session_key)
        if _browser_session_is_connected(session):
            if background_browser and session.spawned is not None:
                await _minimize_browser_context_windows(session.context)
            return session

        if session is not None:
            await _discard_browser_session(session_key, session)

        _check_interrupted()
        playwright = await _await_interruptible(async_playwright_factory().start())
        try:
            browser, context, spawned = await _connect_browser(
                playwright,
                connection_mode,
                cdp_base,
                browser_executable,
                user_data_dir,
                background_browser=background_browser,
            )
        except BaseException:
            with contextlib.suppress(Exception):
                await playwright.stop()
            raise

        session = _BrowserSession(session_key, playwright, browser, context, spawned)
        _BROWSER_SESSIONS[session_key] = session
        return session
    finally:
        lock.release()

async def _maybe_close_spawned_browser_session(session, keep_browser_open):
    if session is None or bool(keep_browser_open) or session.spawned is None:
        return

    lock = _browser_page_pool_lock()
    await _lock_acquire_interruptible(lock)
    try:
        _prune_session_page_pool(session)
        if session.leased_page_ids:
            return
        _BROWSER_SESSIONS.pop(session.key, None)
    finally:
        lock.release()

    await _discard_browser_session(session.key, session)

__all__ = [name for name in globals() if not name.startswith("__")]

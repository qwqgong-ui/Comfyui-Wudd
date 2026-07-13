"""Browser runtime state, interruption, and process helpers."""

from .browser_1_scripts import *

def _hash_value(hasher, value):
    if hasattr(value, "detach") and hasattr(value, "cpu"):
        arr = value.detach().cpu().numpy()
        hasher.update(str(arr.shape).encode("utf-8"))
        hasher.update(arr.tobytes())
        return
    if isinstance(value, np.ndarray):
        hasher.update(str(value.shape).encode("utf-8"))
        hasher.update(value.tobytes())
        return
    if isinstance(value, dict):
        for key in sorted(value):
            _hash_value(hasher, key)
            _hash_value(hasher, value[key])
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _hash_value(hasher, item)
        return
    hasher.update(str(value).encode("utf-8"))
    hasher.update(b"\x00")


def _stable_hash(*args, **kwargs):
    hasher = hashlib.sha256()
    _hash_value(hasher, args)
    _hash_value(hasher, kwargs)
    return hasher.hexdigest()


def _browser_execution_lock():
    loop = asyncio.get_running_loop()
    key = id(loop)
    lock = _BROWSER_EXECUTION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _BROWSER_EXECUTION_LOCKS[key] = lock
    return lock


def _browser_page_pool_lock():
    loop = asyncio.get_running_loop()
    key = id(loop)
    lock = _BROWSER_PAGE_POOL_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _BROWSER_PAGE_POOL_LOCKS[key] = lock
    return lock


class _ChatGPTRunState:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.owner = None
        self.count = 0


def _chatgpt_run_state():
    loop = asyncio.get_running_loop()
    key = id(loop)
    state = _CHATGPT_RUN_STATES.get(key)
    if state is None:
        state = _ChatGPTRunState()
        _CHATGPT_RUN_STATES[key] = state
    return state


async def _acquire_chatgpt_run_slot(unique_id):
    owner = str(unique_id or "__unknown_chatgpt_browser__")
    state = _chatgpt_run_state()
    async with state.condition:
        while state.owner is not None and state.owner != owner:
            await _condition_wait_interruptible(state.condition)
        state.owner = owner
        state.count += 1
    return owner


async def _release_chatgpt_run_slot(owner):
    state = _chatgpt_run_state()
    async with state.condition:
        if state.owner != owner:
            return
        state.count = max(0, state.count - 1)
        if state.count == 0:
            state.owner = None
            state.condition.notify_all()


class _BrowserSession:
    def __init__(self, key, playwright, browser, context, spawned):
        self.key = key
        self.playwright = playwright
        self.browser = browser
        self.context = context
        self.spawned = spawned
        self.page_pool = []
        self.leased_page_ids = set()


def _browser_session_key(cdp_url):
    cdp_base, _, _ = _normalize_cdp_url(cdp_url)
    return (id(asyncio.get_running_loop()), cdp_base)


def _browser_session_is_connected(session):
    if session is None or session.browser is None:
        return False
    try:
        is_connected = getattr(session.browser, "is_connected", None)
        if callable(is_connected):
            return bool(is_connected())
    except Exception:
        return False
    return True


async def _discard_browser_session(session_key, session):
    current = _BROWSER_SESSIONS.get(session_key)
    if current is session:
        _BROWSER_SESSIONS.pop(session_key, None)
    if session is None:
        return
    with contextlib.suppress(Exception):
        if session.browser is not None:
            await session.browser.close()
    if session.spawned is not None and session.spawned.poll() is None:
        with contextlib.suppress(Exception):
            session.spawned.terminate()
    with contextlib.suppress(Exception):
        if session.playwright is not None:
            await session.playwright.stop()


def _normalize_parallel_pages(value):
    try:
        return max(1, min(8, int(value)))
    except (TypeError, ValueError):
        return 2


def _check_interrupted():
    if comfy_model_management is not None:
        comfy_model_management.throw_exception_if_processing_interrupted()


async def _sleep_interruptible(seconds, interval=0.25):
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        _check_interrupted()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(float(interval), remaining))


def _consume_task_exception(task):
    with contextlib.suppress(BaseException):
        task.result()


_NO_EVALUATE_ARG = object()


def _is_transient_page_navigation_error(exc):
    message = str(exc)
    transient_fragments = (
        "Execution context was destroyed",
        "most likely because of a navigation",
        "Cannot find context with specified id",
        "Frame was detached",
    )
    return any(fragment in message for fragment in transient_fragments)


async def _await_interruptible(awaitable, interval=0.25):
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            _check_interrupted()
            done, _ = await asyncio.wait({task}, timeout=float(interval))
            if done:
                break
        _check_interrupted()
        return await task
    except BaseException:
        if not task.done():
            task.cancel()
            task.add_done_callback(_consume_task_exception)
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        raise


async def _condition_wait_interruptible(condition, interval=0.25):
    while True:
        _check_interrupted()
        try:
            await asyncio.wait_for(condition.wait(), timeout=float(interval))
            return
        except asyncio.TimeoutError:
            continue


async def _lock_acquire_interruptible(lock):
    task = asyncio.ensure_future(lock.acquire())
    acquired = False
    try:
        while not task.done():
            _check_interrupted()
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if done:
                break
        acquired = bool(await task)
        _check_interrupted()
    except BaseException:
        if acquired:
            lock.release()
        elif task.done():
            with contextlib.suppress(BaseException):
                if task.result():
                    lock.release()
        else:
            task.cancel()
            task.add_done_callback(_consume_task_exception)
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        raise


async def _wait_for_page_navigation_settled(page, timeout_seconds=10.0):
    if page is None or _page_is_closed(page):
        return
    try:
        await _await_interruptible(
            page.wait_for_load_state(
                "domcontentloaded",
                timeout=max(1000, int(float(timeout_seconds) * 1000)),
            ),
        )
    except Exception:
        pass
    await _sleep_interruptible(0.2)


async def _page_evaluate_with_navigation_retry(
    page,
    script,
    arg=_NO_EVALUATE_ARG,
    attempts=4,
    settle_timeout_seconds=10.0,
):
    last_error = None
    attempts_count = max(1, int(attempts))
    for attempt in range(attempts_count):
        _check_interrupted()
        try:
            if arg is _NO_EVALUATE_ARG:
                return await _await_interruptible(page.evaluate(script))
            return await _await_interruptible(page.evaluate(script, arg))
        except Exception as exc:
            last_error = exc
            if not _is_transient_page_navigation_error(exc) or attempt >= attempts_count - 1:
                raise
            await _wait_for_page_navigation_settled(page, settle_timeout_seconds)
    if last_error is not None:
        raise last_error
    return None


def _normalize_cdp_url(cdp_url):
    cdp_url = str(cdp_url or "").strip() or DEFAULT_CDP_URL
    if not cdp_url.startswith(("http://", "https://")):
        cdp_url = "http://" + cdp_url

    parsed = urlparse(cdp_url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    return f"{scheme}://{host}:{port}", host, port


def _cdp_version_url(cdp_url):
    base, _, _ = _normalize_cdp_url(cdp_url)
    return base.rstrip("/") + "/json/version"


def _is_chatgpt_page_url(url):
    try:
        host = urlparse(str(url or "")).hostname or ""
    except Exception:
        return False
    return host == "chatgpt.com" or host.endswith(".chatgpt.com") or host == "chat.openai.com"


def _is_cdp_ready(cdp_url):
    try:
        with urlopen(_cdp_version_url(cdp_url), timeout=1.0) as response:
            json.loads(response.read().decode("utf-8", errors="replace"))
            return True
    except (OSError, URLError, json.JSONDecodeError):
        return False


def _wait_for_cdp(cdp_url, timeout_seconds):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        _check_interrupted()
        if _is_cdp_ready(cdp_url):
            return
        time.sleep(0.25)
    raise TimeoutError(f"Browser CDP endpoint did not become ready: {_cdp_version_url(cdp_url)}")


def _browser_label(browser_name):
    return "Microsoft Edge" if browser_name == "edge" else "Google Chrome"


def _cdp_launch_failure_message(browser_name, cdp_url, user_data_dir=None, returncode=None):
    label = _browser_label(browser_name)
    detail = ""
    if returncode is not None:
        detail = f" Browser process exited with code {returncode}."
    profile_detail = ""
    if user_data_dir:
        profile_detail = f" User data dir: {user_data_dir}."
    return (
        f"{label} did not expose a CDP endpoint at {_cdp_version_url(cdp_url)}.{detail} "
        f"This node starts {label} with its own user-data-dir.{profile_detail} "
        "Make sure this same user-data-dir is not already open and the CDP port is free."
    )


def _wait_for_launched_cdp(browser_name, cdp_url, process, timeout_seconds, user_data_dir=None):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        _check_interrupted()
        if _is_cdp_ready(cdp_url):
            return
        if process is not None and process.poll() is not None:
            if process.returncode not in (0, None):
                raise RuntimeError(
                    _cdp_launch_failure_message(browser_name, cdp_url, user_data_dir, process.returncode)
                )
        time.sleep(0.25)
    raise TimeoutError(_cdp_launch_failure_message(browser_name, cdp_url, user_data_dir))


def _port_is_free(host, port):
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return False
    except OSError:
        return True


def _expand_path(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path or "").strip())))


def _browser_profiles_root():
    return os.path.join(folder_paths.get_user_directory(), "wudd_browser_profiles")


def _resolve_user_data_dir(user_data_dir):
    value = str(user_data_dir or DEFAULT_BROWSER_USER_DATA_DIR).strip() or DEFAULT_BROWSER_USER_DATA_DIR
    expanded = os.path.expandvars(os.path.expanduser(value))
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    return os.path.abspath(os.path.join(_browser_profiles_root(), expanded))


def _browser_user_data_dir_is_locked(user_data_dir):
    for marker in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        if os.path.exists(os.path.join(user_data_dir, marker)):
            return True
    return False


def _browser_process_names(browser_name):
    if sys.platform == "win32":
        if browser_name == "edge":
            return ["msedge.exe"]
        return ["chrome.exe", "chromium.exe"]
    if sys.platform == "darwin":
        if browser_name == "edge":
            return ["Microsoft Edge"]
        return ["Google Chrome", "Chromium"]
    if browser_name == "edge":
        return ["microsoft-edge", "microsoft-edge-stable", "msedge"]
    return ["chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def _powershell_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _kill_browser_processes_for_user_data_dir(browser_name, user_data_dir):
    names = _browser_process_names(browser_name)
    if sys.platform == "win32":
        ps_names = "@(" + ",".join(_powershell_quote(name) for name in names) + ")"
        ps_dir = _powershell_quote(os.path.abspath(user_data_dir))
        script = (
            f"$names = {ps_names}; "
            f"$dir = {ps_dir}; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $names -contains $_.Name -and $_.CommandLine -and "
            "$_.CommandLine.ToLower().Contains($dir.ToLower()) } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        with contextlib.suppress(Exception):
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8.0,
                creationflags=CREATE_NO_WINDOW,
            )
        return

    with contextlib.suppress(Exception):
        subprocess.run(
            ["pkill", "-f", os.path.abspath(user_data_dir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )


def _cleanup_failed_browser_launch(browser_name, process, user_data_dir):
    if process is not None and process.poll() is None:
        with contextlib.suppress(Exception):
            process.terminate()
    _kill_browser_processes_for_user_data_dir(browser_name, user_data_dir)


async def _launch_browser_and_wait(browser_name, cdp_base, browser_executable, user_data_dir, background_browser=False):
    user_data_dir = _resolve_user_data_dir(user_data_dir)
    spawned = _launch_browser(
        browser_name,
        cdp_base,
        browser_executable,
        user_data_dir,
        background_browser=background_browser,
    )
    try:
        await _await_interruptible(
            asyncio.to_thread(_wait_for_launched_cdp, browser_name, cdp_base, spawned, 30, user_data_dir)
        )
    except BaseException:
        _cleanup_failed_browser_launch(browser_name, spawned, user_data_dir)
        raise
    return spawned


def _candidate_paths(browser_name):
    paths = []
    if browser_name == "edge":
        paths.extend([
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
        ])
        if sys.platform == "win32":
            paths.extend([
                os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            ])
        elif sys.platform == "darwin":
            paths.append("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        else:
            paths.extend([
                shutil.which("microsoft-edge"),
                shutil.which("microsoft-edge-stable"),
            ])
    else:
        paths.extend([
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ])
        if sys.platform == "win32":
            paths.extend([
                os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            ])
        elif sys.platform == "darwin":
            paths.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return [path for path in paths if path]


def _resolve_browser_executable(browser_name, browser_executable):
    override = str(browser_executable or "").strip()
    if override:
        path = _expand_path(override)
        if os.path.isfile(path):
            return path
        raise ValueError(f"Browser executable does not exist: {path}")

    for path in _candidate_paths(browser_name):
        if os.path.isfile(path):
            return path

    label = "Microsoft Edge" if browser_name == "edge" else "Google Chrome/Chromium"
    raise ValueError(
        f"{label} executable was not found. Set browser_executable to the full browser path."
    )


def _launch_browser(
    browser_name,
    cdp_url,
    browser_executable,
    user_data_dir,
    background_browser=False,
):
    cdp_base, host, port = _normalize_cdp_url(cdp_url)
    if _is_cdp_ready(cdp_base):
        return None
    if not _port_is_free(host, port):
        raise RuntimeError(
            f"Port {host}:{port} is already in use, but it is not a Chrome CDP endpoint."
        )
    user_data_dir = _resolve_user_data_dir(user_data_dir)
    if _browser_user_data_dir_is_locked(user_data_dir):
        raise RuntimeError(_cdp_launch_failure_message(browser_name, cdp_base, user_data_dir))

    executable = _resolve_browser_executable(browser_name, browser_executable)
    os.makedirs(user_data_dir, exist_ok=True)

    cmd = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    if background_browser:
        cmd.append("--start-minimized")
    cmd.append("about:blank")

    startupinfo = None
    if sys.platform == "win32" and background_browser:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 7  # SW_SHOWMINNOACTIVE

    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        startupinfo=startupinfo,
    )

def _page_is_closed(page):
    try:
        return page.is_closed()
    except Exception:
        return True

__all__ = [name for name in globals() if not name.startswith("__")]

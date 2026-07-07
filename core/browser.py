"""
Browser automation nodes for ComfyUI-Wudd.

This module drives the user's own Chrome/Edge browser through the Chrome
DevTools Protocol. It does not handle credentials; the user keeps ChatGPT
logged in inside the browser profile used by the node.
"""

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import numpy as np
import folder_paths
from PIL import Image

from .common import CREATE_NO_WINDOW, WUDD_CATEGORY, tensor_to_pil

try:
    import comfy.model_management as comfy_model_management
except Exception:
    comfy_model_management = None


BROWSER_CATEGORY = f"{WUDD_CATEGORY}/Browser"
DEFAULT_CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_BROWSER_USER_DATA_DIR = "chatgpt"
BROWSER_CONNECTION_MODES = [
    "connect_or_launch_edge",
    "connect_or_launch_chrome",
    "connect_cdp",
    "launch_chrome",
    "launch_edge",
]
SUBMIT_ACTIONS = ["press_enter", "click_send_button"]
CHATGPT_TAB_REFRESH_SECONDS = 180.0
CHATGPT_RETRY_CLICK_COOLDOWN_SECONDS = 5.0
IMAGE_GENERATION_FAILURE_PHRASES = (
    "由于我这边发生了错误，我未能生成图片",
    "我未能生成图片",
    "未能生成图片",
    "生成图片时出错",
    "生成图像时出错",
    "couldn't generate image",
    "couldn't generate the image",
    "could not generate image",
    "could not generate the image",
    "unable to generate image",
    "unable to generate the image",
    "failed to generate image",
    "failed to generate the image",
    "wasn't able to generate image",
    "wasn't able to generate the image",
    "was not able to generate image",
    "was not able to generate the image",
)
_BROWSER_EXECUTION_LOCKS = {}
_BROWSER_PAGE_POOL_LOCKS = {}
_CHATGPT_RUN_STATES = {}
_BROWSER_SESSIONS = {}

COMPOSER_SELECTORS = [
    '#prompt-textarea[contenteditable="true"]',
    'textarea#prompt-textarea',
    '[data-testid="composer"] [contenteditable="true"]',
    'form [contenteditable="true"][role="textbox"]',
    '[contenteditable="true"][role="textbox"]',
    'textarea[placeholder*="Message"]',
    'textarea[placeholder*="Send"]',
    'textarea',
]

SEND_BUTTON_SELECTORS = [
    '[data-testid="send-button"]',
    'button[aria-label*="Send"]',
    'button[aria-label*="send"]',
    'button[aria-label*="发送"]',
]

ATTACH_BUTTON_SELECTORS = [
    'button[aria-label*="Attach"]',
    'button[aria-label*="attach"]',
    'button[aria-label*="Add"]',
    'button[aria-label*="add"]',
    'button[aria-label*="file"]',
    'button[aria-label*="File"]',
    'button[aria-label*="photo"]',
    'button[aria-label*="Photo"]',
    'button[aria-label*="Upload"]',
    'button[aria-label*="upload"]',
    'button[aria-label*="添加"]',
    'button[aria-label*="上传"]',
    'button[title*="Attach"]',
    'button[title*="Upload"]',
    '[data-testid="attach-file-button"]',
    '[data-testid*="attach"]',
    '[data-testid*="upload"]',
    '[data-testid*="composer-plus"]',
    '[data-testid*="plus"]',
]

ASSISTANT_TEXT_SCRIPT = """
() => {
  const texts = [];
  const seen = new Set();

  function isVisible(el) {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      rect.width > 0 &&
      rect.height > 0;
  }

  function addText(el) {
    if (!el || seen.has(el) || !isVisible(el)) return;
    seen.add(el);
    const text = (el.innerText || el.textContent || "").trim();
    if (text) texts.push(text);
  }

  for (const el of document.querySelectorAll('[data-message-author-role="assistant"]')) {
    addText(el);
  }

  if (texts.length) return texts;

  for (const article of document.querySelectorAll("article")) {
    const label = (
      article.getAttribute("aria-label") ||
      article.getAttribute("data-testid") ||
      ""
    ).toLowerCase();
    if (label.includes("assistant") || label.includes("chatgpt")) {
      addText(article);
    }
  }

  return texts;
}
"""

STREAMING_SCRIPT = """
() => {
  const buttons = Array.from(document.querySelectorAll("button"));
  return buttons.some((button) => {
    const label = (
      button.getAttribute("aria-label") ||
      button.getAttribute("title") ||
      button.innerText ||
      ""
    ).toLowerCase();
    return label.includes("stop") ||
      label.includes("停止") ||
      label.includes("cancel response");
  });
}
"""

STOP_RESPONSE_SCRIPT = """
() => {
  const buttons = Array.from(document.querySelectorAll("button"));
  for (const button of buttons.reverse()) {
    const label = (
      button.getAttribute("aria-label") ||
      button.getAttribute("title") ||
      button.innerText ||
      ""
    ).toLowerCase();
    if (
      label.includes("stop") ||
      label.includes("停止") ||
      label.includes("cancel response")
    ) {
      button.click();
      return true;
    }
  }
  return false;
}
"""

DISMISS_FREQUENT_REQUEST_NOTICE_SCRIPT = """
() => {
  const noticePhrases = [
    "请求过于频繁",
    "过于频繁",
    "请稍等几分钟后再重试",
    "too frequent",
    "rate limit",
    "temporarily limited",
    "please wait a few minutes",
  ];
  const dismissLabels = [
    "明白了",
    "知道了",
    "我知道了",
    "got it",
    "ok",
    "okay",
  ];

  function textOf(el) {
    return (el && (el.innerText || el.textContent || "") || "").trim();
  }

  function normalizedText(el) {
    return textOf(el).replace(/\\s+/g, " ").toLowerCase();
  }

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      rect.width > 0 &&
      rect.height > 0;
  }

  function hasNoticeText(el) {
    const text = normalizedText(el);
    return noticePhrases.some((phrase) => text.includes(phrase.toLowerCase()));
  }

  function isDismissButton(button) {
    const label = (
      button.getAttribute("aria-label") ||
      button.getAttribute("title") ||
      textOf(button)
    ).trim().toLowerCase();
    return dismissLabels.some((candidate) => label.includes(candidate));
  }

  function noticeContainerFor(button) {
    let el = button;
    for (let depth = 0; el && el !== document.body && el !== document.documentElement && depth < 12; depth += 1) {
      if (isVisible(el) && hasNoticeText(el)) {
        const rect = el.getBoundingClientRect();
        const role = (el.getAttribute("role") || "").toLowerCase();
        const ariaModal = (el.getAttribute("aria-modal") || "").toLowerCase() === "true";
        const text = textOf(el);
        const noticeSized = rect.width <= window.innerWidth * 0.98 &&
          rect.height <= window.innerHeight * 0.85;
        if ((role === "dialog" || ariaModal || noticeSized) && text.length <= 2000) {
          return el;
        }
      }
      el = el.parentElement;
    }
    return null;
  }

  const buttons = Array.from(document.querySelectorAll("button"));
  for (const button of buttons.reverse()) {
    if (!isVisible(button) || !isDismissButton(button)) continue;
    if (!noticeContainerFor(button)) continue;
    button.click();
    return true;
  }
  return false;
}
"""

CLICK_CHATGPT_RETRY_BUTTON_SCRIPT = """
() => {
  const retryLabels = [
    "retry",
    "try again",
    "重试",
    "再试一次",
    "重新尝试"
  ];

  function textOf(el) {
    return (el && (el.innerText || el.textContent || "") || "").trim();
  }

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      rect.width > 0 &&
      rect.height > 0;
  }

  function isDisabled(el) {
    return Boolean(
      el.disabled ||
      (el.getAttribute("aria-disabled") || "").toLowerCase() === "true" ||
      (el.getAttribute("disabled") !== null)
    );
  }

  function buttonLabel(button) {
    return (
      button.getAttribute("aria-label") ||
      button.getAttribute("title") ||
      button.getAttribute("data-testid") ||
      textOf(button)
    ).replace(/\\s+/g, " ").trim().toLowerCase();
  }

  function isRetryButton(button) {
    const label = buttonLabel(button);
    return retryLabels.some((candidate) => label.includes(candidate));
  }

  function assistantScopes() {
    const selectors = [
      '[data-message-author-role="assistant"]',
      'article[aria-label*="assistant" i]',
      'article[data-testid*="assistant" i]',
      'article'
    ];
    const seen = new Set();
    const scopes = [];
    for (const selector of selectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (seen.has(el) || !isVisible(el)) continue;
        seen.add(el);
        scopes.push(el);
      }
    }
    return scopes.slice(-3).reverse();
  }

  const scopes = assistantScopes();
  const searchRoots = scopes.length ? scopes : [document.body];
  for (const root of searchRoots) {
    const buttons = Array.from(root.querySelectorAll('button, [role="button"]'));
    for (const button of buttons.reverse()) {
      if (!isVisible(button) || isDisabled(button) || !isRetryButton(button)) continue;
      button.click();
      return true;
    }
  }
  return false;
}
"""

COMPOSER_STATE_SCRIPT = """
(el) => {
  if (!el) return { ready: false, text: "" };
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const tag = (el.tagName || "").toLowerCase();
  const ariaDisabled = (el.getAttribute("aria-disabled") || "").toLowerCase() === "true";
  const editable = tag === "textarea" || tag === "input" || el.isContentEditable;
  const disabled = Boolean(el.disabled || el.readOnly || ariaDisabled);
  const visible = style.display !== "none" &&
    style.visibility !== "hidden" &&
    rect.width > 0 &&
    rect.height > 0;
  const form = el.closest("form");
  const busy = Boolean(
    (form && (form.getAttribute("aria-busy") || "").toLowerCase() === "true") ||
    (form && form.querySelector('[aria-busy="true"]'))
  );
  const text = tag === "textarea" || tag === "input"
    ? (el.value || "")
    : (el.innerText || el.textContent || "");
  return { ready: Boolean(visible && editable && !disabled && !busy), text };
}
"""

SET_COMPOSER_TEXT_SCRIPT = """
(el, text) => {
  if (!el) return "";
  const tag = (el.tagName || "").toLowerCase();
  el.focus();

  if (tag === "textarea" || tag === "input") {
    const proto = tag === "textarea" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, text);
    } else {
      el.value = text;
    }
  } else {
    el.textContent = text;
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  try {
    el.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      inputType: "insertText",
      data: text
    }));
  } catch (_) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return tag === "textarea" || tag === "input"
    ? (el.value || "")
    : (el.innerText || el.textContent || "");
}
"""

MEDIA_TO_DATA_URL_SCRIPT = """
async (el) => {
  const tag = (el.tagName || "").toLowerCase();

  function canvasFromImage(img) {
    const width = img.naturalWidth || img.videoWidth || img.width;
    const height = img.naturalHeight || img.videoHeight || img.height;
    if (!width || !height) return null;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, width, height);
    return canvas;
  }

  function blobToDataURL(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  if (tag === "canvas") {
    return el.toDataURL("image/png");
  }

  if (tag !== "img") return null;

  try {
    if (el.decode) await el.decode();
  } catch (_) {}

  const src = el.currentSrc || el.src || "";
  if (src.startsWith("data:")) return src;

  if (src) {
    try {
      const response = await fetch(src, { credentials: "include" });
      if (response.ok) {
        return await blobToDataURL(await response.blob());
      }
    } catch (_) {}
  }

  const canvas = canvasFromImage(el);
  return canvas ? canvas.toDataURL("image/png") : null;
}
"""

URL_TO_DATA_URL_SCRIPT = """
async (url) => {
  function blobToDataURL(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) return null;
  return await blobToDataURL(await response.blob());
}
"""

GENERATED_IMAGE_URLS_SCRIPT = """
() => {
  const needles = [
    "/backend-api/estuary/content",
    "/backend-api/files",
    "/backend-api/file",
    "files.oaiusercontent.com",
    "oaiusercontent.com",
    "oaidalle",
    "dalle"
  ];
  const urls = [];
  const seen = new Set();

  function add(url) {
    if (!url || url.startsWith("data:") || url.startsWith("blob:")) return;
    try {
      url = new URL(url, document.baseURI).href;
    } catch (_) {
      return;
    }
    const value = url.toLowerCase();
    if (!needles.some((needle) => value.includes(needle))) return;
    if (seen.has(url)) return;
    seen.add(url);
    urls.push(url);
  }

  function addSrcset(srcset) {
    if (!srcset) return;
    for (const part of srcset.split(",")) {
      add(part.trim().split(/\\s+/)[0]);
    }
  }

  function isUploadThumbnail(img) {
    const alt = (img.getAttribute("alt") || "").trim().toLowerCase();
    const filename = alt.split(/[\\\\/]/).pop();
    return /^chatgpt_[a-z0-9_-]+\\.(png|jpe?g|webp)$/.test(filename);
  }

  function hasGeneratedAlt(img) {
    const alt = img.getAttribute("alt") || "";
    return alt.includes("已生成图片") ||
      alt.toLowerCase().includes("generated image");
  }

  function isGeneratedCandidate(img) {
    if (isUploadThumbnail(img)) return false;
    if (img.closest('[data-message-author-role="user"]')) return false;
    if (img.closest('form')) return false;

    const src = img.currentSrc || img.src || img.getAttribute("src") || "";
    if (!src) return false;
    const value = src.toLowerCase();
    if (!needles.some((needle) => value.includes(needle))) return false;

    const rect = img.getBoundingClientRect();
    if ((rect.width || 0) < 64 || (rect.height || 0) < 64) return false;
    return hasGeneratedAlt(img) || !img.closest('[data-message-author-role]');
  }

  for (const img of document.querySelectorAll("img")) {
    if (!isGeneratedCandidate(img)) continue;
    add(img.currentSrc || img.src);
    addSrcset(img.getAttribute("srcset"));
  }

  return urls;
}
"""

IMAGE_ELEMENT_METADATA_SCRIPT = """
(el) => {
  const tag = (el.tagName || "").toLowerCase();
  let url = "";
  if (tag === "img" || tag === "source") {
    url = el.currentSrc || el.src || el.getAttribute("src") || "";
  }
  return {
    tag,
    url,
    alt: el.getAttribute("alt") || "",
    className: String(el.getAttribute("class") || ""),
    role: el.closest('[data-message-author-role]')?.getAttribute('data-message-author-role') || "",
    inForm: !!el.closest("form"),
    naturalWidth: el.naturalWidth || 0,
    naturalHeight: el.naturalHeight || 0
  };
}
"""


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


def _make_upload_png(image):
    temp_dir = os.path.join(folder_paths.get_temp_directory(), "wudd_chatgpt_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="chatgpt_", suffix=".png", dir=temp_dir)
    os.close(fd)
    tensor_to_pil(image).convert("RGBA").save(path, format="PNG")
    return path


def _image_frames(image):
    if image is None:
        return []
    shape = getattr(image, "shape", None)
    if shape is not None and len(shape) == 4 and int(shape[0]) > 1:
        return [image[index:index + 1] for index in range(int(shape[0]))]
    return [image]


def _numbered_image_items(values):
    if not values:
        return []
    return sorted(
        (
            (str(key), value)
            for key, value in values.items()
            if str(key).startswith("image_") and value is not None
        ),
        key=lambda item: int(item[0].split("_", 1)[1]) if item[0].split("_", 1)[1].isdigit() else 10**9,
    )


def _input_image_frames(image=None, images=None, extra_images=None):
    frames = []
    if image is not None:
        frames.extend(_image_frames(image))

    if isinstance(images, dict):
        for _, value in _numbered_image_items(images):
            frames.extend(_image_frames(value))
    elif isinstance(images, (list, tuple)):
        for value in images:
            frames.extend(_image_frames(value))
    elif images is not None:
        frames.extend(_image_frames(images))

    for _, value in _numbered_image_items(extra_images):
        frames.extend(_image_frames(value))
    return frames


def _make_upload_pngs(frames):
    return [_make_upload_png(frame) for frame in frames]


def _clean_response_text(text):
    text = str(text or "").strip()
    if not text:
        return ""

    blocked_lines = {
        "copy",
        "good response",
        "bad response",
        "read aloud",
        "regenerate",
        "retry",
        "share",
    }
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() in blocked_lines:
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


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


async def _assistant_texts(page):
    try:
        values = await _page_evaluate_with_navigation_retry(page, ASSISTANT_TEXT_SCRIPT)
    except Exception as exc:
        if _is_transient_page_navigation_error(exc):
            return []
        raise
    return [_clean_response_text(value) for value in values if _clean_response_text(value)]


def _pil_images_to_tensor_batch(images):
    import torch

    if not images:
        return torch.zeros((1, 1, 1, 3), dtype=torch.float32)

    max_width = max(image.width for image in images)
    max_height = max(image.height for image in images)
    tensors = []
    for image in images:
        canvas = Image.new("RGB", (max_width, max_height), (0, 0, 0))
        canvas.paste(image.convert("RGB"), (0, 0))
        arr = np.asarray(canvas).astype(np.float32) / 255.0
        tensors.append(torch.from_numpy(arr).unsqueeze(0))
    return torch.cat(tensors, dim=0)


def _looks_like_chatgpt_image_url(url):
    value = str(url or "").lower()
    return any(
        marker in value
        for marker in (
            "/backend-api/estuary/content",
            "/backend-api/files",
            "/backend-api/file",
            "files.oaiusercontent.com",
            "oaiusercontent.com",
            "oaidalle",
            "dalle",
        )
    )


def _normalize_image_url(url):
    return str(url or "").replace("&amp;", "&").strip()


def _chatgpt_file_id(url):
    try:
        query = urlparse(_normalize_image_url(url)).query
    except Exception:
        return ""
    for part in query.split("&"):
        if part.startswith("id="):
            return part[3:]
    return ""


def _image_url_keys(url):
    value = _normalize_image_url(url)
    keys = set()
    if value:
        keys.add(value)
    file_id = _chatgpt_file_id(value)
    if file_id:
        keys.add(f"id:{file_id}")
    return keys


def _image_url_key_set(urls):
    keys = set()
    for url in urls or []:
        keys.update(_image_url_keys(url))
    return keys


def _image_url_is_ignored(url, ignored_keys):
    if not ignored_keys:
        return False
    return bool(_image_url_keys(url) & set(ignored_keys))


def _looks_like_upload_thumbnail(meta):
    alt = str((meta or {}).get("alt") or "").strip().lower()
    filename = alt.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if filename.startswith("chatgpt_") and filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return True
    return False


def _looks_like_generated_image_meta(meta):
    alt = str((meta or {}).get("alt") or "")
    url = str((meta or {}).get("url") or "")
    if not _looks_like_chatgpt_image_url(url):
        return False
    if _looks_like_upload_thumbnail(meta):
        return False
    if str((meta or {}).get("role") or "").lower() == "user":
        return False
    if bool((meta or {}).get("inForm")):
        return False
    return "已生成图片" in alt or "generated image" in alt.lower() or not (meta or {}).get("role")


def _is_candidate_generated_image(image, strong_match=False):
    if image is None:
        return False
    min_edge = 64 if strong_match else 128
    min_area = 4096 if strong_match else 65536
    return image.width >= min_edge and image.height >= min_edge and image.width * image.height >= min_area


def _image_fingerprint(image):
    rgb = image.convert("RGB")
    hasher = hashlib.sha256()
    hasher.update(f"{rgb.width}x{rgb.height}".encode("ascii"))
    hasher.update(rgb.tobytes())
    return hasher.hexdigest()


def _dedupe_images(images, ignored_fingerprints=None):
    deduped = []
    seen = set()
    ignored_fingerprints = set(ignored_fingerprints or [])
    for image in images:
        if image is None:
            continue
        key = _image_fingerprint(image)
        if key in ignored_fingerprints:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(image)
    return deduped


def _prompt_likely_requests_image(prompt):
    text = str(prompt or "").lower()
    keywords = (
        "image",
        "picture",
        "photo",
        "render",
        "illustration",
        "poster",
        "thumbnail",
        "cover",
        "product shot",
        "\u56fe",
        "\u56fe\u7247",
        "\u56fe\u50cf",
        "\u4e3b\u56fe",
        "\u6d77\u62a5",
        "\u6444\u5f71",
    )
    return any(keyword in text for keyword in keywords)


def _image_generation_failed_text(text):
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return False
    return any(phrase.lower() in normalized for phrase in IMAGE_GENERATION_FAILURE_PHRASES)


def _pil_from_data_url(data_url):
    if not data_url or "," not in data_url:
        return None
    header, payload = data_url.split(",", 1)
    if ";base64" not in header:
        return None
    raw = base64.b64decode(payload)
    image = Image.open(BytesIO(raw))
    image.load()
    return image.convert("RGB")


def _pil_from_response_bytes(raw):
    image = Image.open(BytesIO(raw))
    image.load()
    return image.convert("RGB")


class _ImageResponseCollector:
    def __init__(self, page, ignored_urls=None, ignored_fingerprints=None):
        self.page = page
        self.images = []
        self._raw_hashes = set()
        self.ignored_keys = _image_url_key_set(ignored_urls)
        self.ignored_fingerprints = set(ignored_fingerprints or [])
        self._tasks = set()
        self._started = False

    def start(self):
        if self._started:
            return
        self.page.on("response", self._on_response)
        self._started = True

    def stop(self):
        if not self._started:
            return
        try:
            self.page.remove_listener("response", self._on_response)
        except Exception:
            pass
        self._started = False

    def _on_response(self, response):
        task = asyncio.create_task(self._capture_response(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _capture_response(self, response):
        try:
            url = response.url
            if _image_url_is_ignored(url, self.ignored_keys):
                return
            headers = response.headers or {}
            content_type = str(headers.get("content-type") or "").lower()
            strong_match = _looks_like_chatgpt_image_url(url)
            if not strong_match and not content_type.startswith("image/"):
                return
            if content_type.startswith("image/svg"):
                return

            raw = await response.body()
            if not raw:
                return
            raw_hash = hashlib.sha256(raw).hexdigest()
            if raw_hash in self._raw_hashes:
                return

            image = _pil_from_response_bytes(raw)
            if not _is_candidate_generated_image(image, strong_match=strong_match):
                return
            if _image_fingerprint(image) in self.ignored_fingerprints:
                return

            self._raw_hashes.add(raw_hash)
            self.images.append(image)
        except Exception:
            return

    async def drain(self, timeout_seconds=2.0):
        if self._tasks:
            done, pending = await asyncio.wait(
                list(self._tasks),
                timeout=max(0.1, float(timeout_seconds)),
            )
            for task in done:
                try:
                    task.result()
                except Exception:
                    pass
        return list(self.images)


async def _media_locator_to_pil(locator, timeout_ms, allow_screenshot=True):
    try:
        data_url = await _await_interruptible(
            locator.evaluate(MEDIA_TO_DATA_URL_SCRIPT, timeout=timeout_ms),
        )
        image = _pil_from_data_url(data_url)
        if image is not None:
            return image
    except Exception:
        pass

    if not allow_screenshot:
        return None

    raw_png = await _await_interruptible(locator.screenshot(type="png", timeout=timeout_ms))
    image = Image.open(BytesIO(raw_png))
    image.load()
    return image.convert("RGB")


async def _url_to_pil_via_page(page, url, timeout_seconds):
    try:
        data_url = await _await_interruptible(
            asyncio.wait_for(
                _page_evaluate_with_navigation_retry(
                    page,
                    URL_TO_DATA_URL_SCRIPT,
                    url,
                    settle_timeout_seconds=min(10.0, max(1.0, float(timeout_seconds))),
                ),
                timeout=max(1.0, float(timeout_seconds)),
            )
        )
        return _pil_from_data_url(data_url)
    except Exception:
        return None


async def _page_known_image_urls(page):
    try:
        urls = await _page_evaluate_with_navigation_retry(page, GENERATED_IMAGE_URLS_SCRIPT)
    except Exception:
        return []
    return [_normalize_image_url(url) for url in urls or []]


async def _generated_url_images(
    page,
    timeout_seconds,
    ignored_keys=None,
    ignored_fingerprints=None,
):
    urls = await _page_known_image_urls(page)
    images = []
    seen_urls = set()
    per_url_timeout = min(10.0, max(1.0, float(timeout_seconds)))
    for url in reversed(urls or []):
        if url in seen_urls:
            continue
        if _image_url_is_ignored(url, ignored_keys):
            continue
        seen_urls.add(url)
        image = await _url_to_pil_via_page(page, url, per_url_timeout)
        if not _is_candidate_generated_image(image, strong_match=True):
            continue
        if _image_fingerprint(image) in set(ignored_fingerprints or []):
            continue
        images.append(image)
        if len(images) >= 4:
            break
    return list(reversed(_dedupe_images(images, ignored_fingerprints=ignored_fingerprints)))


async def _visible_media_images(
    container,
    timeout_seconds,
    selector="img, canvas",
    min_size=32,
    ignored_keys=None,
    require_generated_meta=False,
):
    timeout_ms = max(1000, int(float(timeout_seconds) * 1000))
    images = []
    media = container.locator(selector)
    count = await _await_interruptible(media.count())
    for index in range(count):
        locator = media.nth(index)
        try:
            if not await _await_interruptible(locator.is_visible()):
                continue
            meta = await _await_interruptible(
                locator.evaluate(IMAGE_ELEMENT_METADATA_SCRIPT, timeout=timeout_ms),
            )
            if _image_url_is_ignored((meta or {}).get("url"), ignored_keys):
                continue
            if _looks_like_upload_thumbnail(meta):
                continue
            if str((meta or {}).get("role") or "").lower() == "user":
                continue
            if bool((meta or {}).get("inForm")):
                continue
            if require_generated_meta and not _looks_like_generated_image_meta(meta):
                continue
            box = await _await_interruptible(locator.bounding_box())
            if not box or box["width"] < min_size or box["height"] < min_size:
                continue
            await _await_interruptible(locator.scroll_into_view_if_needed(timeout=timeout_ms))
            natural_width = int((meta or {}).get("naturalWidth") or 0)
            natural_height = int((meta or {}).get("naturalHeight") or 0)
            url = (meta or {}).get("url")
            allow_screenshot = not (
                _looks_like_chatgpt_image_url(url) and
                (natural_width < min_size or natural_height < min_size)
            )
            image = await _media_locator_to_pil(locator, timeout_ms, allow_screenshot=allow_screenshot)
            if image is not None:
                images.append(image)
        except Exception:
            continue
    return images


async def _visible_generated_media_images(
    page,
    timeout_seconds,
    ignored_keys=None,
    ignored_fingerprints=None,
):
    selector = (
        'img[src*="/backend-api/estuary/content"], '
        'img[src*="backend-api/estuary/content"], '
        'img[src*="/backend-api/files"], '
        'img[src*="backend-api/files"], '
        'img[src*="/backend-api/file"], '
        'img[src*="backend-api/file"], '
        'img[src*="files.oaiusercontent.com"], '
        'img[src*="oaiusercontent.com"], '
        'img[src*="oaidalle"], '
        'img[src*="dalle"], '
        'img[alt*="\u5df2\u751f\u6210\u56fe\u7247"]'
    )
    images = await _visible_media_images(
        page,
        timeout_seconds,
        selector=selector,
        min_size=64,
        ignored_keys=ignored_keys,
        require_generated_meta=True,
    )
    return _dedupe_images(
        (image for image in images if _is_candidate_generated_image(image, strong_match=True)),
        ignored_fingerprints=ignored_fingerprints,
    )


async def _latest_assistant_images(
    page,
    timeout_seconds,
    ignored_keys=None,
    ignored_fingerprints=None,
):
    images = await _visible_generated_media_images(
        page,
        timeout_seconds,
        ignored_keys=ignored_keys,
        ignored_fingerprints=ignored_fingerprints,
    )
    if images:
        return images

    images = await _generated_url_images(
        page,
        timeout_seconds,
        ignored_keys=ignored_keys,
        ignored_fingerprints=ignored_fingerprints,
    )
    if images:
        return images

    containers = page.locator('[data-message-author-role="assistant"]')
    count = await _await_interruptible(containers.count())
    for index in range(count - 1, -1, -1):
        images = await _visible_media_images(
            containers.nth(index),
            timeout_seconds,
            ignored_keys=ignored_keys,
        )
        if images:
            return images

    articles = page.locator("article")
    count = await _await_interruptible(articles.count())
    for index in range(count - 1, -1, -1):
        article = articles.nth(index)
        try:
            label = (
                (await _await_interruptible(article.get_attribute("aria-label"))) or
                (await _await_interruptible(article.get_attribute("data-testid"))) or
                ""
            ).lower()
            if "assistant" not in label and "chatgpt" not in label:
                continue
        except Exception:
            continue

        images = await _visible_media_images(article, timeout_seconds, ignored_keys=ignored_keys)
        if images:
            return images

    return []


async def _collect_response_images(
    page,
    collector,
    timeout_seconds,
    ignored_keys=None,
    ignored_fingerprints=None,
):
    images = []
    effective_ignored_keys = ignored_keys or (collector.ignored_keys if collector is not None else None)
    effective_ignored_fingerprints = (
        ignored_fingerprints or
        (collector.ignored_fingerprints if collector is not None else None)
    )
    if collector is not None:
        await collector.drain(0.25)
    try:
        images.extend(await _latest_assistant_images(
            page,
            timeout_seconds,
            ignored_keys=effective_ignored_keys,
            ignored_fingerprints=effective_ignored_fingerprints,
        ))
    except Exception as exc:
        if not _is_transient_page_navigation_error(exc):
            raise
        await _wait_for_page_navigation_settled(page, min(10.0, max(1.0, float(timeout_seconds))))
    return _dedupe_images(images, ignored_fingerprints=effective_ignored_fingerprints)


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
        await collector.drain(2.0)
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


def _page_is_closed(page):
    try:
        return page.is_closed()
    except Exception:
        return True


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


class WuddChatGPTBrowser:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "connection_mode": (BROWSER_CONNECTION_MODES, {"default": "connect_or_launch_edge"}),
                "cdp_url": ("STRING", {"default": DEFAULT_CDP_URL, "advanced": True}),
                "wait_timeout_seconds": (
                    "INT",
                    {"default": 300, "min": 10, "max": 3600, "step": 1, "advanced": True},
                ),
                "stable_seconds": (
                    "FLOAT",
                    {"default": 2.0, "min": 0.5, "max": 30.0, "step": 0.5, "advanced": True},
                ),
                "upload_wait_seconds": (
                    "FLOAT",
                    {"default": 4.0, "min": 0.0, "max": 120.0, "step": 0.5, "advanced": True},
                ),
                "new_chat": ("BOOLEAN", {"default": True}),
                "submit_action": (SUBMIT_ACTIONS, {"default": "press_enter"}),
                "keep_browser_open": ("BOOLEAN", {"default": True, "advanced": True}),
                "background_browser": ("BOOLEAN", {"default": True, "advanced": True}),
                "parallel_pages": (
                    "INT",
                    {"default": 2, "min": 1, "max": 8, "step": 1, "advanced": True},
                ),
                "run_id": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 2147483647,
                        "step": 1,
                        "control_after_generate": True,
                    },
                ),
            },
            "optional": {
                "image": ("IMAGE",),
                "browser_executable": ("STRING", {"default": "", "advanced": True}),
                "close_page_after_run": ("BOOLEAN", {"default": True, "advanced": True}),
                "image_error_retries": ("INT", {"default": 2, "min": 0, "max": 10, "step": 1, "advanced": True}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING", "IMAGE", "INT")
    RETURN_NAMES = ("text", "conversation_url", "images", "image_count")
    FUNCTION = "submit"
    CATEGORY = BROWSER_CATEGORY

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

"""
Browser automation nodes for ComfyUI-Wudd.

This module drives the user's own Chrome/Edge browser through the Chrome
DevTools Protocol. It does not handle credentials; the user keeps ChatGPT
logged in inside the browser profile used by the node.
"""

import asyncio
import base64
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

from .nodes_common import CREATE_NO_WINDOW, WUDD_CATEGORY, tensor_to_pil


BROWSER_CATEGORY = f"{WUDD_CATEGORY}/Browser"
DEFAULT_CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
BROWSER_CONNECTION_MODES = [
    "connect_or_launch_edge",
    "connect_or_launch_chrome",
    "connect_cdp",
    "launch_chrome",
    "launch_edge",
]
SUBMIT_ACTIONS = ["press_enter", "click_send_button"]
BROWSER_PROFILE_MODES = [
    "wudd_isolated_profile",
    "browser_default_profile",
    "custom_user_data_dir",
]
_BROWSER_EXECUTION_LOCKS = {}

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


def _normalize_url(url, default):
    url = str(url or "").strip() or default
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


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
        if _is_cdp_ready(cdp_url):
            return
        time.sleep(0.25)
    raise TimeoutError(f"Browser CDP endpoint did not become ready: {_cdp_version_url(cdp_url)}")


def _port_is_free(host, port):
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return False
    except OSError:
        return True


def _expand_path(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path or "").strip())))


def _default_user_data_dir(browser_name):
    root = os.path.join(folder_paths.get_user_directory(), "wudd_browser_profiles")
    return os.path.join(root, browser_name)


def _default_browser_user_data_dir(browser_name):
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if browser_name == "edge":
            return os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
        return os.path.join(local_appdata, "Google", "Chrome", "User Data")

    if sys.platform == "darwin":
        home = os.path.expanduser("~")
        if browser_name == "edge":
            return os.path.join(home, "Library", "Application Support", "Microsoft Edge")
        return os.path.join(home, "Library", "Application Support", "Google", "Chrome")

    home = os.path.expanduser("~")
    if browser_name == "edge":
        return os.path.join(home, ".config", "microsoft-edge")
    return os.path.join(home, ".config", "google-chrome")


def _resolve_profile_options(browser_name, profile_mode, user_data_dir, profile_directory):
    profile_mode = str(profile_mode or "wudd_isolated_profile").strip()
    profile_directory = str(profile_directory or "").strip()

    if profile_mode == "custom_user_data_dir":
        if not str(user_data_dir or "").strip():
            raise ValueError("user_data_dir is required when profile_mode is custom_user_data_dir.")
        return _expand_path(user_data_dir), profile_directory

    if profile_mode == "browser_default_profile":
        profile_dir = _default_browser_user_data_dir(browser_name)
        if not os.path.isdir(profile_dir):
            raise ValueError(
                f"Default {browser_name} profile directory was not found: {profile_dir}"
            )
        return profile_dir, profile_directory or "Default"

    if profile_mode != "wudd_isolated_profile":
        raise ValueError(f"Unsupported profile_mode: {profile_mode}")

    profile_dir = _default_user_data_dir(browser_name)
    return profile_dir, profile_directory


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
    profile_mode,
    user_data_dir,
    profile_directory,
    chatgpt_url,
):
    cdp_base, host, port = _normalize_cdp_url(cdp_url)
    if _is_cdp_ready(cdp_base):
        return None
    if not _port_is_free(host, port):
        raise RuntimeError(
            f"Port {host}:{port} is already in use, but it is not a Chrome CDP endpoint."
        )

    executable = _resolve_browser_executable(browser_name, browser_executable)
    profile_dir, resolved_profile_directory = _resolve_profile_options(
        browser_name,
        profile_mode,
        user_data_dir,
        profile_directory,
    )
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        chatgpt_url,
    ]
    if resolved_profile_directory:
        cmd.insert(-1, f"--profile-directory={resolved_profile_directory}")
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def _make_upload_png(image):
    temp_dir = os.path.join(folder_paths.get_temp_directory(), "wudd_chatgpt_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="chatgpt_", suffix=".png", dir=temp_dir)
    os.close(fd)
    tensor_to_pil(image).convert("RGBA").save(path, format="PNG")
    return path


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
    last_error = None
    while time.monotonic() < deadline:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count - 1, -1, -1):
                    candidate = locator.nth(index)
                    if await candidate.is_visible():
                        return candidate
            except Exception as exc:
                last_error = exc
        await asyncio.sleep(0.4)
    if last_error:
        raise TimeoutError(f"Timed out finding ChatGPT composer: {last_error}") from last_error
    raise TimeoutError("Timed out finding ChatGPT composer. Log in to ChatGPT in the opened browser.")


async def _assistant_texts(page):
    values = await page.evaluate(ASSISTANT_TEXT_SCRIPT)
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


def _split_image_batch(image):
    if image is None:
        return [None]
    shape = getattr(image, "shape", None)
    if shape is None or len(shape) != 4 or int(shape[0]) <= 1:
        return [image]
    return [image[index:index + 1] for index in range(int(shape[0]))]


def _merge_batch_results(results):
    import torch

    texts = []
    urls = []
    image_batches = []
    total_count = 0

    for index, result in enumerate(results, start=1):
        text, url, images, image_count = result
        if text:
            texts.append(f"[{index}] {text}")
        if url:
            urls.append(str(url))
        count = int(image_count or 0)
        if count > 0:
            image_batches.append(images[:count])
            total_count += count

    if not image_batches:
        merged_images = torch.zeros((1, 1, 1, 3), dtype=torch.float32)
    else:
        max_height = max(int(batch.shape[1]) for batch in image_batches)
        max_width = max(int(batch.shape[2]) for batch in image_batches)
        padded = []
        for batch in image_batches:
            for image in batch:
                canvas = torch.zeros((max_height, max_width, image.shape[-1]), dtype=image.dtype)
                canvas[: image.shape[0], : image.shape[1], : image.shape[2]] = image
                padded.append(canvas.unsqueeze(0))
        merged_images = torch.cat(padded, dim=0)

    return ("\n\n".join(texts), "\n".join(urls), merged_images, total_count)


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
        data_url = await locator.evaluate(MEDIA_TO_DATA_URL_SCRIPT, timeout=timeout_ms)
        image = _pil_from_data_url(data_url)
        if image is not None:
            return image
    except Exception:
        pass

    if not allow_screenshot:
        return None

    raw_png = await locator.screenshot(type="png", timeout=timeout_ms)
    image = Image.open(BytesIO(raw_png))
    image.load()
    return image.convert("RGB")


async def _url_to_pil_via_page(page, url, timeout_seconds):
    try:
        data_url = await asyncio.wait_for(
            page.evaluate(URL_TO_DATA_URL_SCRIPT, url),
            timeout=max(1.0, float(timeout_seconds)),
        )
        return _pil_from_data_url(data_url)
    except Exception:
        return None


async def _page_known_image_urls(page):
    try:
        urls = await page.evaluate(GENERATED_IMAGE_URLS_SCRIPT)
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
    count = await media.count()
    for index in range(count):
        locator = media.nth(index)
        try:
            if not await locator.is_visible():
                continue
            meta = await locator.evaluate(IMAGE_ELEMENT_METADATA_SCRIPT, timeout=timeout_ms)
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
            box = await locator.bounding_box()
            if not box or box["width"] < min_size or box["height"] < min_size:
                continue
            await locator.scroll_into_view_if_needed(timeout=timeout_ms)
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
    count = await containers.count()
    for index in range(count - 1, -1, -1):
        images = await _visible_media_images(
            containers.nth(index),
            timeout_seconds,
            ignored_keys=ignored_keys,
        )
        if images:
            return images

    articles = page.locator("article")
    count = await articles.count()
    for index in range(count - 1, -1, -1):
        article = articles.nth(index)
        try:
            label = (
                (await article.get_attribute("aria-label")) or
                (await article.get_attribute("data-testid")) or
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
    images.extend(await _latest_assistant_images(
        page,
        timeout_seconds,
        ignored_keys=effective_ignored_keys,
        ignored_fingerprints=effective_ignored_fingerprints,
    ))
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

        await asyncio.sleep(0.75)

    if collector is not None:
        await collector.drain(2.0)
    return []


async def _is_streaming(page):
    try:
        return bool(await page.evaluate(STREAMING_SCRIPT))
    except Exception:
        return False


async def _attach_image_file(page, file_path, timeout_seconds):
    timeout_ms = max(1000, int(float(timeout_seconds) * 1000))
    file_inputs = page.locator('input[type="file"]')
    try:
        if await file_inputs.count() > 0:
            await file_inputs.first.set_input_files(file_path, timeout=timeout_ms)
            return
    except Exception:
        pass

    for selector in ATTACH_BUTTON_SELECTORS:
        button = page.locator(selector).last
        try:
            if await button.count() == 0 or not await button.is_visible():
                continue
            async with page.expect_file_chooser(timeout=timeout_ms) as file_chooser_info:
                await button.click(timeout=timeout_ms)
            file_chooser = await file_chooser_info.value
            await file_chooser.set_files(file_path)
            return
        except Exception:
            try:
                if await file_inputs.count() > 0:
                    await file_inputs.first.set_input_files(file_path, timeout=timeout_ms)
                    return
            except Exception:
                pass

    raise RuntimeError("Could not find ChatGPT's file upload control.")


async def _fill_composer(composer, page, prompt):
    await composer.click()
    try:
        await composer.fill("")
    except Exception:
        modifier = "Meta" if sys.platform == "darwin" else "Control"
        await page.keyboard.press(f"{modifier}+A")
        await page.keyboard.press("Backspace")

    if prompt:
        try:
            await composer.fill(prompt)
        except Exception:
            await page.keyboard.insert_text(prompt)


async def _click_send_button(page, timeout_seconds, required=True):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        for selector in SEND_BUTTON_SELECTORS:
            try:
                button = page.locator(selector).last
                if await button.count() == 0:
                    continue
                if await button.is_visible() and await button.is_enabled():
                    await button.click()
                    return True
            except Exception:
                pass
        await asyncio.sleep(0.25)
    if required:
        raise TimeoutError("Timed out finding an enabled ChatGPT send button.")
    return False


async def _response_started(page, previous_count):
    texts = await _assistant_texts(page)
    return len(texts) > previous_count or await _is_streaming(page)


async def _wait_for_response(page, previous_count, timeout_seconds, stable_seconds):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    stable_seconds = max(0.5, float(stable_seconds))
    last_text = ""
    last_change = time.monotonic()
    started = False

    while time.monotonic() < deadline:
        texts = await _assistant_texts(page)
        current = ""
        if len(texts) > previous_count:
            started = True
            current = texts[-1]
        elif started and texts:
            current = texts[-1]

        if current and current != last_text:
            last_text = current
            last_change = time.monotonic()

        streaming = await _is_streaming(page)
        if last_text and started and not streaming and time.monotonic() - last_change >= stable_seconds:
            return last_text

        await asyncio.sleep(0.5)

    if last_text:
        return last_text
    raise TimeoutError("Timed out waiting for ChatGPT response text.")


async def _wait_for_response_result(page, collector, previous_count, timeout_seconds, stable_seconds, prompt):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    stable_seconds = max(0.5, float(stable_seconds))
    image_expected = _prompt_likely_requests_image(prompt)
    last_text = ""
    last_change = time.monotonic()
    started = False
    text_ready = False

    while time.monotonic() < deadline:
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

        if current and current != last_text:
            last_text = current
            last_change = time.monotonic()
            text_ready = False

        streaming = await _is_streaming(page)
        if last_text and started and not streaming and time.monotonic() - last_change >= stable_seconds:
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

        await asyncio.sleep(0.5 if not text_ready else 1.0)

    images = await _collect_response_images(page, collector, min(5.0, float(timeout_seconds)))
    if images or last_text:
        return last_text, images
    raise TimeoutError("Timed out waiting for ChatGPT response text or image.")


async def _goto_chatgpt(page, chatgpt_url):
    last_error = None
    for wait_until in ("domcontentloaded", "commit"):
        try:
            await page.goto(chatgpt_url, wait_until=wait_until, timeout=60000)
            return
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if "ERR_ABORTED" in message and _is_chatgpt_page_url(page.url):
                return
            await asyncio.sleep(0.75)
    if last_error is not None:
        raise last_error


async def _get_chatgpt_page(context, chatgpt_url, new_chat):
    if new_chat:
        page = await context.new_page()
        await _goto_chatgpt(page, chatgpt_url)
        await page.bring_to_front()
        return page

    candidates = [
        page for page in context.pages
        if _is_chatgpt_page_url(page.url)
    ]
    page = candidates[-1] if candidates else await context.new_page()
    await page.bring_to_front()
    if not _is_chatgpt_page_url(page.url):
        await _goto_chatgpt(page, chatgpt_url)
    return page


async def _connect_browser(
    playwright,
    connection_mode,
    cdp_url,
    browser_executable,
    profile_mode,
    user_data_dir,
    profile_directory,
    chatgpt_url,
):
    cdp_base, _, _ = _normalize_cdp_url(cdp_url)
    spawned = None

    if connection_mode == "connect_or_launch_chrome":
        if not _is_cdp_ready(cdp_base):
            spawned = _launch_browser(
                "chrome",
                cdp_base,
                browser_executable,
                profile_mode,
                user_data_dir,
                profile_directory,
                chatgpt_url,
            )
            await asyncio.to_thread(_wait_for_cdp, cdp_base, 30)
    elif connection_mode == "connect_or_launch_edge":
        if not _is_cdp_ready(cdp_base):
            spawned = _launch_browser(
                "edge",
                cdp_base,
                browser_executable,
                profile_mode,
                user_data_dir,
                profile_directory,
                chatgpt_url,
            )
            await asyncio.to_thread(_wait_for_cdp, cdp_base, 30)
    elif connection_mode == "launch_chrome":
        spawned = _launch_browser(
            "chrome",
            cdp_base,
            browser_executable,
            profile_mode,
            user_data_dir,
            profile_directory,
            chatgpt_url,
        )
        await asyncio.to_thread(_wait_for_cdp, cdp_base, 30)
    elif connection_mode == "launch_edge":
        spawned = _launch_browser(
            "edge",
            cdp_base,
            browser_executable,
            profile_mode,
            user_data_dir,
            profile_directory,
            chatgpt_url,
        )
        await asyncio.to_thread(_wait_for_cdp, cdp_base, 30)

    browser = await playwright.chromium.connect_over_cdp(cdp_base)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    return browser, context, spawned


class WuddChatGPTBrowser:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "connection_mode": (BROWSER_CONNECTION_MODES, {"default": "connect_or_launch_edge"}),
                "chatgpt_url": ("STRING", {"default": DEFAULT_CHATGPT_URL, "advanced": True}),
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
                "profile_mode": (BROWSER_PROFILE_MODES, {"default": "wudd_isolated_profile", "advanced": True}),
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
                "user_data_dir": ("STRING", {"default": "", "advanced": True}),
                "profile_directory": ("STRING", {"default": "Default", "advanced": True}),
            },
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
        chatgpt_url,
        cdp_url,
        wait_timeout_seconds,
        stable_seconds,
        upload_wait_seconds,
        new_chat,
        submit_action,
        keep_browser_open,
        profile_mode,
        run_id,
        image=None,
        browser_executable="",
        user_data_dir="",
        profile_directory="Default",
    ):
        prompt = str(prompt or "")
        if not prompt.strip() and image is None:
            raise ValueError("Prompt or image is required.")
        if connection_mode not in BROWSER_CONNECTION_MODES:
            raise ValueError(f"Unsupported connection_mode: {connection_mode}")
        if submit_action not in SUBMIT_ACTIONS:
            raise ValueError(f"Unsupported submit_action: {submit_action}")
        if profile_mode not in BROWSER_PROFILE_MODES:
            raise ValueError(f"Unsupported profile_mode: {profile_mode}")

        image_batch = _split_image_batch(image)
        if len(image_batch) > 1:
            results = []
            for single_image in image_batch:
                results.append(await self.submit(
                    prompt,
                    connection_mode,
                    chatgpt_url,
                    cdp_url,
                    wait_timeout_seconds,
                    stable_seconds,
                    upload_wait_seconds,
                    new_chat,
                    submit_action,
                    keep_browser_open,
                    profile_mode,
                    run_id,
                    image=single_image,
                    browser_executable=browser_executable,
                    user_data_dir=user_data_dir,
                    profile_directory=profile_directory,
                ))
            return _merge_batch_results(results)

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ImportError(
                "Wudd ChatGPT Browser requires Playwright. Install it in the ComfyUI "
                "Python environment with: python -m pip install playwright"
            ) from exc

        chatgpt_url = _normalize_url(chatgpt_url, DEFAULT_CHATGPT_URL)
        cdp_base, _, _ = _normalize_cdp_url(cdp_url)
        upload_path = None
        spawned = None
        browser = None
        image_collector = None
        browser_lock = _browser_execution_lock()
        await browser_lock.acquire()
        try:
            playwright = await async_playwright().start()
        except Exception:
            browser_lock.release()
            raise

        try:
            browser, context, spawned = await _connect_browser(
                playwright,
                connection_mode,
                cdp_base,
                browser_executable,
                profile_mode,
                user_data_dir,
                profile_directory,
                chatgpt_url,
            )
            page = await _get_chatgpt_page(context, chatgpt_url, bool(new_chat))
            composer = await _first_visible_locator(page, COMPOSER_SELECTORS, wait_timeout_seconds)
            previous_count = len(await _assistant_texts(page))
            ignored_image_fingerprints = set()

            if image is not None:
                ignored_image_fingerprints.add(_image_fingerprint(tensor_to_pil(image).convert("RGB")))
                upload_path = _make_upload_png(image)
                await _attach_image_file(page, upload_path, wait_timeout_seconds)
                if float(upload_wait_seconds) > 0:
                    await asyncio.sleep(float(upload_wait_seconds))

            ignored_image_urls = await _page_known_image_urls(page)
            image_collector = _ImageResponseCollector(
                page,
                ignored_urls=ignored_image_urls,
                ignored_fingerprints=ignored_image_fingerprints,
            )
            image_collector.start()
            await _fill_composer(composer, page, prompt)

            if submit_action == "click_send_button":
                await _click_send_button(page, wait_timeout_seconds)
            else:
                await composer.press("Enter")
                await asyncio.sleep(2.0)
                if not await _response_started(page, previous_count):
                    await _click_send_button(page, 5, required=False)

            text, images = await _wait_for_response_result(
                page,
                image_collector,
                previous_count,
                wait_timeout_seconds,
                stable_seconds,
                prompt,
            )
            return (text, page.url, _pil_images_to_tensor_batch(images), len(images))
        finally:
            if image_collector is not None:
                image_collector.stop()

            if upload_path and os.path.exists(upload_path):
                try:
                    os.remove(upload_path)
                except OSError:
                    pass

            if spawned is not None and not bool(keep_browser_open):
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                if spawned.poll() is None:
                    spawned.terminate()
            try:
                await playwright.stop()
            finally:
                browser_lock.release()


__all__ = ["WuddChatGPTBrowser"]

"""Browser upload and response-image helpers."""

from .browser_2_runtime import *

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
    collector_images = []
    effective_ignored_keys = ignored_keys or (collector.ignored_keys if collector is not None else None)
    effective_ignored_fingerprints = (
        ignored_fingerprints or
        (collector.ignored_fingerprints if collector is not None else None)
    )
    if collector is not None:
        collector_images = await collector.drain(0.25)
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
    # DOM 抓图保持原有优先级；网络响应仅作为补充，并沿用输入图忽略与像素去重规则。
    images.extend(collector_images)
    return _dedupe_images(images, ignored_fingerprints=effective_ignored_fingerprints)

__all__ = [name for name in globals() if not name.startswith("__")]

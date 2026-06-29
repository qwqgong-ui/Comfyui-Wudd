import asyncio
import base64
import hashlib
import http.client
import json
import os
import ssl
from io import BytesIO
from urllib.parse import urljoin, urlparse

import numpy as np
from PIL import Image

from .common import WUDD_CATEGORY, tensor_to_base64_png


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_PATH = "chat/completions"

TEXT_CATEGORY = f"{WUDD_CATEGORY}/OpenRouter/Text"
IMAGE_CATEGORY = f"{WUDD_CATEGORY}/OpenRouter/Image"

MAX_TEXT_IMAGE_INPUTS = 16
MAX_IMAGE_NODE_INPUTS = 16

REASONING_EFFORTS = ["none", "minimal", "low", "medium", "high"]
TEXT_RESPONSE_FORMATS = ["text", "json_object"]
IMAGE_RESPONSE_MODALITIES = ["IMAGE+TEXT", "IMAGE"]
STANDARD_ASPECT_RATIOS = [
    "auto",
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
]
EXTENDED_ASPECT_RATIOS = [
    *STANDARD_ASPECT_RATIOS,
    "1:4",
    "4:1",
    "1:8",
    "8:1",
]
GPT_IMAGE_SIZES = ["auto", "1K", "2K", "4K"]
GEMINI_IMAGE_SIZES = ["auto", "0.5K", "1K", "2K", "4K"]

OPENAI_GPT_TEXT_MODELS = ["openai/gpt-5.5", "openai/gpt-5.5-pro"]
OPENAI_GPT_IMAGE_MODELS = ["openai/gpt-5.4-image-2"]
CLAUDE_TEXT_MODELS = ["anthropic/claude-opus-4.7", "anthropic/claude-sonnet-4.6"]
GEMINI_TEXT_MODELS = ["google/gemini-3.1-pro-preview", "google/gemini-3-flash-preview"]
GEMINI_IMAGE_MODELS = ["google/gemini-3-pro-image-preview", "google/gemini-3.1-flash-image-preview"]


def _image_port_inputs(max_images):
    return {f"image_{i}": ("IMAGE",) for i in range(1, max_images + 1)}


def _api_runtime_inputs():
    return {
        "base_url": (
            "STRING",
            {
                "default": OPENROUTER_BASE_URL,
                "advanced": True,
            },
        ),
        "timeout_seconds": (
            "INT",
            {
                "default": 300,
                "min": 5,
                "max": 3600,
                "step": 1,
                "advanced": True,
            },
        ),
        "verify_ssl": (
            "BOOLEAN",
            {
                "default": True,
                "advanced": True,
            },
        ),
    }


def _system_and_extra_inputs():
    return {
        "system_prompt": (
            "STRING",
            {
                "default": "",
                "multiline": True,
            },
        ),
        "extra_body_json": (
            "STRING",
            {
                "default": "",
                "multiline": True,
                "advanced": True,
            },
        ),
    }


def _normalize_base_url(base_url):
    base_url = (base_url or "").strip() or OPENROUTER_BASE_URL
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    return base_url.rstrip("/")


def _build_chat_url(base_url):
    base_url = _normalize_base_url(base_url)
    if base_url.endswith("/chat/completions"):
        return base_url
    return urljoin(base_url + "/", OPENROUTER_CHAT_PATH)


def _resolve_api_key(api_key):
    api_key = (api_key or "").strip() or os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OpenRouter API key is required. Set api_key or OPENROUTER_API_KEY.")
    return api_key


def _validate_model(model):
    model = (model or "").strip()
    if not model:
        raise ValueError("OpenRouter model id cannot be empty.")
    return model


def _validate_prompt(prompt):
    prompt = str(prompt or "")
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")
    return prompt


def _parse_json_object(text, field_name):
    text = (text or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be a valid JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object.")
    return value


def _split_stop_sequences(stop_sequences):
    values = []
    for line in str(stop_sequences or "").splitlines():
        line = line.strip()
        if line:
            values.append(line)
    return values


def _add_reasoning(payload, reasoning_effort):
    if reasoning_effort and reasoning_effort != "none":
        payload["reasoning"] = {"effort": reasoning_effort}


def _add_response_format(payload, response_format):
    if response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}


def _add_stop_sequences(payload, stop_sequences):
    stop = _split_stop_sequences(stop_sequences)
    if stop:
        payload["stop"] = stop


def _add_image_config(payload, model, aspect_ratio, image_size):
    if image_size == "0.5K" and model != "google/gemini-3.1-flash-image-preview":
        raise ValueError("0.5K image_size is only supported by google/gemini-3.1-flash-image-preview.")

    image_config = {}
    if aspect_ratio and aspect_ratio != "auto":
        image_config["aspect_ratio"] = aspect_ratio
    if image_size and image_size != "auto":
        image_config["image_size"] = image_size
    if image_config:
        payload["image_config"] = image_config


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


def _flatten_image_inputs(values, max_images):
    frames = []
    for image in values:
        if image is None:
            continue
        shape = getattr(image, "shape", None)
        if shape is None:
            raise ValueError("Image input is not a tensor-like object.")
        if len(shape) == 4:
            for index in range(shape[0]):
                frames.append(image[index])
                if len(frames) >= max_images:
                    return frames
        elif len(shape) == 3:
            frames.append(image)
            if len(frames) >= max_images:
                return frames
        else:
            raise ValueError(f"Unsupported IMAGE tensor shape: {tuple(shape)}")
    return frames


def _collect_numbered_images(kwargs, max_images):
    values = [kwargs.get(f"image_{i}") for i in range(1, max_images + 1)]
    return _flatten_image_inputs(values, max_images)


def _image_frame_to_data_url(image):
    return f"data:image/png;base64,{tensor_to_base64_png(image)}"


def _build_user_content(prompt, images):
    content = [{"type": "text", "text": prompt}]
    for image in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_frame_to_data_url(image),
                },
            }
        )
    return content


def _build_messages(prompt, system_prompt="", images=None):
    messages = []
    system_prompt = str(system_prompt or "").strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if images:
        messages.append({"role": "user", "content": _build_user_content(prompt, images)})
    else:
        messages.append({"role": "user", "content": prompt})
    return messages


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _http_json(url, api_key, payload, timeout_seconds=300, verify_ssl=True):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "ComfyUI-Wudd",
    }
    body = _json_dumps(payload).encode("utf-8")
    status, raw_body = _http_request(
        url,
        method="POST",
        headers=headers,
        body=body,
        timeout_seconds=timeout_seconds,
        verify_ssl=verify_ssl,
    )
    if status >= 400:
        raise ValueError(f"OpenRouter API error {status}: {raw_body}")
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenRouter returned invalid JSON: {raw_body}") from exc


def _http_bytes(url, timeout_seconds=300, verify_ssl=True):
    status, raw_body = _http_request(
        url,
        method="GET",
        headers={},
        body=None,
        timeout_seconds=timeout_seconds,
        verify_ssl=verify_ssl,
        decode_body=False,
    )
    if status >= 400:
        raise ValueError(f"Image download failed with HTTP {status}.")
    return raw_body


def _http_request(url, method, headers, body, timeout_seconds, verify_ssl, decode_body=True):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {url}")

    ssl_context = None
    if parsed.scheme == "https" and not verify_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    conn = None
    try:
        if parsed.scheme == "https":
            conn = connection_cls(parsed.hostname, port, timeout=timeout_seconds, context=ssl_context)
        else:
            conn = connection_cls(parsed.hostname, port, timeout=timeout_seconds)
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        if decode_body:
            raw = raw.decode("utf-8", errors="replace")
        return resp.status, raw
    except ssl.SSLError as exc:
        raise ValueError(f"SSL error while reaching OpenRouter: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Failed to reach OpenRouter: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


def _first_message(response_json):
    choices = response_json.get("choices") or []
    if not choices:
        return {}
    return choices[0].get("message") or {}


def _extract_text_from_content(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in ("text", "output_text") and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _extract_text(response_json):
    texts = []
    for choice in response_json.get("choices") or []:
        message = choice.get("message") or {}
        text = _extract_text_from_content(message.get("content"))
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def _extract_reasoning(response_json):
    message = _first_message(response_json)
    reasoning = message.get("reasoning") or response_json.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning
    if reasoning:
        return _json_dumps(reasoning)

    details = message.get("reasoning_details") or response_json.get("reasoning_details")
    if not details:
        return ""
    if isinstance(details, str):
        return details
    if isinstance(details, list):
        parts = []
        for item in details:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("summary")
                parts.append(text if isinstance(text, str) else _json_dumps(item))
        return "\n".join(part for part in parts if part)
    return _json_dumps(details)


def _extract_image_url_from_value(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("url"), str):
        return value["url"]
    if isinstance(value.get("b64_json"), str):
        return f"data:image/png;base64,{value['b64_json']}"
    return None


def _extract_generated_image_urls(response_json):
    urls = []
    for choice in response_json.get("choices") or []:
        message = choice.get("message") or {}

        for image in message.get("images") or []:
            if not isinstance(image, dict):
                continue
            url = _extract_image_url_from_value(image.get("image_url")) or _extract_image_url_from_value(image)
            if url:
                urls.append(url)

        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") in ("image_url", "output_image", "image"):
                    url = (
                        _extract_image_url_from_value(item.get("image_url"))
                        or _extract_image_url_from_value(item.get("image"))
                        or _extract_image_url_from_value(item)
                    )
                    if url:
                        urls.append(url)
    return urls


def _decode_data_url(data_url):
    try:
        header, data = data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("Invalid data URL returned by OpenRouter.") from exc
    if ";base64" not in header:
        raise ValueError("Only base64 data URLs are supported for returned images.")
    return base64.b64decode(data)


def _load_pil_from_url(image_url, timeout_seconds=300, verify_ssl=True):
    if image_url.startswith("data:"):
        raw = _decode_data_url(image_url)
    else:
        raw = _http_bytes(image_url, timeout_seconds=timeout_seconds, verify_ssl=verify_ssl)
    try:
        image = Image.open(BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except Exception as exc:
        raise ValueError("OpenRouter returned an image that Pillow could not decode.") from exc


def _pil_images_to_tensor_batch(images):
    import torch

    if not images:
        raise ValueError("No images to convert.")

    max_width = max(image.width for image in images)
    max_height = max(image.height for image in images)
    tensors = []
    for image in images:
        canvas = Image.new("RGB", (max_width, max_height), (0, 0, 0))
        canvas.paste(image.convert("RGB"), (0, 0))
        arr = np.asarray(canvas).astype(np.float32) / 255.0
        tensors.append(torch.from_numpy(arr).unsqueeze(0))
    return torch.cat(tensors, dim=0)


class _OpenRouterBase:
    FUNCTION = "generate"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return _stable_hash(cls.__name__, args, kwargs)

    async def _send_chat(self, api_key, base_url, payload, timeout_seconds, verify_ssl):
        api_key = _resolve_api_key(api_key)
        url = _build_chat_url(base_url)
        return await asyncio.to_thread(
            _http_json,
            url,
            api_key,
            payload,
            int(timeout_seconds),
            bool(verify_ssl),
        )

    async def _text_request(
        self,
        prompt,
        api_key,
        model,
        payload_options,
        system_prompt="",
        extra_body_json="",
        images=None,
        base_url=OPENROUTER_BASE_URL,
        timeout_seconds=300,
        verify_ssl=True,
    ):
        prompt = _validate_prompt(prompt)
        model = _validate_model(model)

        payload = {
            "model": model,
            "messages": _build_messages(prompt, system_prompt=system_prompt, images=images),
            "stream": False,
        }
        payload.update(payload_options)
        payload.update(_parse_json_object(extra_body_json, "extra_body_json"))

        response_json = await self._send_chat(api_key, base_url, payload, timeout_seconds, verify_ssl)
        text = _extract_text(response_json)
        if not text:
            raise ValueError(f"No text output found in OpenRouter response: {_json_dumps(response_json)}")
        return text, _extract_reasoning(response_json), response_json.get("id", "")

    async def _image_request(
        self,
        prompt,
        api_key,
        model,
        payload_options,
        system_prompt="",
        extra_body_json="",
        images=None,
        base_url=OPENROUTER_BASE_URL,
        timeout_seconds=300,
        verify_ssl=True,
    ):
        prompt = _validate_prompt(prompt)
        model = _validate_model(model)

        payload = {
            "model": model,
            "messages": _build_messages(prompt, system_prompt=system_prompt, images=images),
            "stream": False,
        }
        payload.update(payload_options)
        payload.update(_parse_json_object(extra_body_json, "extra_body_json"))

        response_json = await self._send_chat(api_key, base_url, payload, timeout_seconds, verify_ssl)
        image_urls = _extract_generated_image_urls(response_json)
        if not image_urls:
            text = _extract_text(response_json).strip()
            if text:
                raise ValueError(f"OpenRouter returned no image. Text response: {text}")
            raise ValueError(f"No image output found in OpenRouter response: {_json_dumps(response_json)}")

        pil_images = await asyncio.gather(
            *[
                asyncio.to_thread(
                    _load_pil_from_url,
                    image_url,
                    int(timeout_seconds),
                    bool(verify_ssl),
                )
                for image_url in image_urls
            ]
        )
        return _pil_images_to_tensor_batch(pil_images), _extract_text(response_json), response_json.get("id", "")


__all__ = [name for name in globals() if not name.startswith("__")]

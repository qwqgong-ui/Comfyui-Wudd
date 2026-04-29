"""
ComfyUI-Wudd — 外部 API 调用类节点。

包含：
    WuddOpenAIGPT54   调用 OpenAI 兼容端点（GPT-5.4 系列），
                      支持 Responses / Chat Completions 两种 api_mode、
                      可选图像输入、Responses 模式异步轮询。
                      generate 为 async，HTTP 调用走线程池，多实例可并发。
                      IS_CHANGED 基于输入做确定性哈希，无变化直接复用缓存。
"""

import asyncio
import hashlib
import json
import ssl
import base64
import http.client
import numpy as np
from io import BytesIO
from PIL import Image
from urllib.parse import urljoin, urlparse

from .nodes_common import WUDD_CATEGORY


class WuddOpenAIGPT54:
    RESPONSES_URL = "https://api.openai.com/v1/responses"
    CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": ""}),
                "base_url": ("STRING", {"default": "https://api.openai.com/v1"}),
                "model": ("STRING", {"default": "gpt-5.4"}),
                "api_mode": (["responses", "chat_completions"], {"default": "responses"}),
                "reasoning_effort": (["none", "low", "medium", "high", "xhigh"], {"default": "medium"}),
                "verbosity": (["low", "medium", "high"], {"default": "medium"}),
                "verify_ssl": ("BOOLEAN", {"default": True}),
                "max_output_tokens": ("INT", {"default": 4096, "min": 16, "max": 131072}),
                "poll_interval": ("FLOAT", {"default": 1.0, "min": 0.2, "max": 10.0, "step": 0.1}),
                "max_wait_seconds": ("INT", {"default": 120, "min": 5, "max": 3600}),
            },
            "optional": {
                "instructions": ("STRING", {"default": "", "multiline": True}),
                "images": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "response_id")
    FUNCTION = "generate"
    CATEGORY = WUDD_CATEGORY

    @staticmethod
    def _validate_api_key(api_key):
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("OpenAI API key is required.")
        return api_key

    @staticmethod
    def _normalize_base_url(base_url):
        base_url = (base_url or "").strip()
        if not base_url:
            return "https://api.openai.com/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        return base_url.rstrip("/")

    @classmethod
    def _build_endpoint(cls, base_url, api_mode, response_id=None):
        if api_mode == "chat_completions":
            return urljoin(base_url + "/", "chat/completions")
        endpoint = urljoin(base_url + "/", "responses")
        if response_id:
            endpoint = f"{endpoint}/{response_id}"
        return endpoint

    @staticmethod
    def _tensor_to_base64_png(image_tensor):
        image_np = (255.0 * image_tensor.cpu().numpy()).clip(0, 255).astype(np.uint8)
        if image_np.shape[-1] == 4:
            mode = "RGBA"
        else:
            mode = "RGB"
        img = Image.fromarray(image_np, mode=mode)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @classmethod
    def _build_input_content(cls, prompt, images=None):
        content = [{"type": "input_text", "text": prompt}]
        if images is not None:
            for i in range(images.shape[0]):
                content.append(
                    {
                        "type": "input_image",
                        "detail": "auto",
                        "image_url": f"data:image/png;base64,{cls._tensor_to_base64_png(images[i])}",
                    }
                )
        return [{"role": "user", "content": content}]

    @staticmethod
    def _extract_text(response_json, api_mode):
        if api_mode == "chat_completions":
            choices = response_json.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                content = message.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    return "".join(text_parts)
            return ""

        output_text = response_json.get("output_text")
        if output_text:
            return output_text

        output = response_json.get("output", [])
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return content.get("text", "")
        return ""

    @staticmethod
    def _http_json(url, api_key, payload=None, method="POST", timeout=300, verify_ssl=True):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {url}")

        ssl_context = None
        if not verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        conn = None
        try:
            if parsed.scheme == "https":
                conn = connection_cls(parsed.hostname, port, timeout=timeout, context=ssl_context)
            else:
                conn = connection_cls(parsed.hostname, port, timeout=timeout)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw_body = resp.read().decode("utf-8", errors="replace")
        except ssl.SSLError as e:
            raise ValueError(f"SSL error while reaching OpenAI-compatible API: {e}") from e
        except OSError as e:
            raise ValueError(f"Failed to reach OpenAI-compatible API: {e}") from e
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

        if resp.status >= 400:
            raise ValueError(f"OpenAI API error {resp.status}: {raw_body}")

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as e:
            raise ValueError(f"OpenAI API returned invalid JSON: {raw_body}") from e

    @classmethod
    async def _wait_for_response(cls, api_key, base_url, response_id, poll_interval, max_wait_seconds, verify_ssl):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_seconds
        while loop.time() < deadline:
            response_json = await asyncio.to_thread(
                cls._http_json,
                cls._build_endpoint(base_url, "responses", response_id),
                api_key,
                None,
                "GET",
                max(30, int(poll_interval * 10)),
                verify_ssl,
            )
            status = response_json.get("status")
            if status in ("completed", "incomplete"):
                return response_json
            if status in ("failed", "cancelled", "canceled"):
                raise ValueError(f"OpenAI response failed with status '{status}': {json.dumps(response_json, ensure_ascii=False)}")
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"Timed out waiting for OpenAI response after {max_wait_seconds} seconds.")

    @classmethod
    def IS_CHANGED(
        cls,
        prompt,
        api_key,
        base_url,
        model,
        api_mode,
        reasoning_effort,
        verbosity,
        verify_ssl,
        max_output_tokens,
        poll_interval,
        max_wait_seconds,
        instructions="",
        images=None,
    ):
        h = hashlib.sha256()
        for part in (
            prompt,
            api_key,
            base_url,
            model,
            api_mode,
            reasoning_effort,
            verbosity,
            str(bool(verify_ssl)),
            str(int(max_output_tokens)),
            f"{float(poll_interval):.6f}",
            str(int(max_wait_seconds)),
            instructions or "",
        ):
            h.update(str(part).encode("utf-8"))
            h.update(b"\x00")
        if images is not None:
            arr = images.cpu().numpy() if hasattr(images, "cpu") else np.asarray(images)
            h.update(str(arr.shape).encode("utf-8"))
            h.update(arr.tobytes())
        return h.hexdigest()

    async def generate(
        self,
        prompt,
        api_key,
        base_url,
        model,
        api_mode,
        reasoning_effort,
        verbosity,
        verify_ssl,
        max_output_tokens,
        poll_interval,
        max_wait_seconds,
        instructions="",
        images=None,
    ):
        api_key = self._validate_api_key(api_key)
        base_url = self._normalize_base_url(base_url)
        prompt = str(prompt or "")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        if api_mode == "chat_completions":
            message_content = [{"type": "text", "text": prompt}]
            if images is not None:
                for i in range(images.shape[0]):
                    message_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{self._tensor_to_base64_png(images[i])}"},
                        }
                    )
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": message_content}],
                "max_completion_tokens": int(max_output_tokens),
            }
            if instructions and instructions.strip():
                payload["messages"].insert(0, {"role": "system", "content": instructions})
            if reasoning_effort != "none":
                payload["reasoning_effort"] = reasoning_effort
            response_json = await asyncio.to_thread(
                self._http_json,
                self._build_endpoint(base_url, api_mode),
                api_key,
                payload,
                "POST",
                300,
                verify_ssl,
            )
            response_id = response_json.get("id", "")
        else:
            payload = {
                "model": model,
                "input": self._build_input_content(prompt, images),
                "max_output_tokens": int(max_output_tokens),
                "store": True,
                "text": {"verbosity": verbosity},
                "reasoning": {"effort": reasoning_effort},
            }
            if instructions and instructions.strip():
                payload["instructions"] = instructions

            response_json = await asyncio.to_thread(
                self._http_json,
                self._build_endpoint(base_url, api_mode),
                api_key,
                payload,
                "POST",
                300,
                verify_ssl,
            )
            response_id = response_json.get("id", "")
            status = response_json.get("status")

            if status not in ("completed", "incomplete"):
                if not response_id:
                    raise ValueError(f"OpenAI API returned no response id: {json.dumps(response_json, ensure_ascii=False)}")
                response_json = await self._wait_for_response(
                    api_key, base_url, response_id, poll_interval, max_wait_seconds, verify_ssl
                )

        text = self._extract_text(response_json, api_mode)
        if not text:
            raise ValueError(f"No text output found in OpenAI response: {json.dumps(response_json, ensure_ascii=False)}")
        return (text, response_json.get("id", response_id))

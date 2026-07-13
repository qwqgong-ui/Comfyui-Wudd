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

from .common import CREATE_NO_WINDOW, tensor_to_pil

try:
    import comfy.model_management as comfy_model_management
except Exception:
    comfy_model_management = None


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

__all__ = [name for name in globals() if not name.startswith("__")]

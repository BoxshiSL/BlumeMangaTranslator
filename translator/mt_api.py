"""Thin HTTP/model helpers used by translator engines."""
from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
import urllib.parse
from html import unescape
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MtApiError(RuntimeError):
    """Raised when translation API/model invocation fails."""


def _post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Any:
    """Perform a JSON POST request with the standard library."""
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
    except urllib.error.HTTPError as exc:  # noqa: BLE001
        raise MtApiError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:  # noqa: BLE001
        raise MtApiError(str(exc)) from exc


def _get_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    """Perform a JSON GET request."""
    req_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
    except urllib.error.HTTPError as exc:  # noqa: BLE001
        raise MtApiError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:  # noqa: BLE001
        raise MtApiError(str(exc)) from exc


def call_mt_api(
    prompt_data: Dict[str, Any],
    engine_id: str,
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    """
    Call an external HTTP MT/LLM endpoint or fall back to a deterministic stub.

    When `endpoint` is provided, performs a POST with the prompt payload and tries
    to extract a translated string from common response shapes:
      - JSON with `translation` / `translated_text` / `text` / `result`
      - plain text body
    """
    text = str(prompt_data.get("text", ""))
    src_lang = str(prompt_data.get("src_lang", ""))
    dst_lang = str(prompt_data.get("dst_lang", ""))

    if endpoint:
        headers = {"X-Engine-Id": engine_id}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key
        payload = {
            "engine_id": engine_id,
            "text": text,
            "src_lang": src_lang,
            "dst_lang": dst_lang,
            "prompt": prompt_data,
        }
        response = _post_json(endpoint, payload, headers=headers)
        if isinstance(response, dict):
            for key in ("translation", "translated_text", "text", "result"):
                if key in response:
                    return str(response[key])
        if isinstance(response, str):
            return response
        raise MtApiError(f"Unexpected response from {endpoint}: {response!r}")

    # Stub fallback (deterministic) if no endpoint is configured.
    if not text:
        return ""
    return f"[{engine_id} {src_lang}->{dst_lang}] {text}"


# -------------------- web translators --------------------
def translate_google_web(text: str, src_lang: str, dst_lang: str) -> str:
    """
    Use the lightweight web client endpoint (translate.googleapis.com) instead of the official API.
    """
    if not text:
        return ""
    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": src_lang,
            "tl": dst_lang,
            "dt": "t",
            "q": text,
        }
    )
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    data = _get_json(url)  # translate.googleapis returns JSON on GET
    if isinstance(data, list) and data and isinstance(data[0], list):
        # data[0] is list of [translated, original, ...]
        parts = [chunk[0] for chunk in data[0] if chunk and isinstance(chunk, list)]
        return unescape("".join(parts))
    raise MtApiError(f"Unexpected Google response: {data!r}")


def translate_yandex_web(text: str, src_lang: str, dst_lang: str) -> str:
    """
    Use Yandex web translation endpoint (non-official) that mimics site requests.
    """
    if not text:
        return ""
    query = urllib.parse.urlencode({"text": text, "lang": f"{src_lang}-{dst_lang}", "srv": "tr-text"})
    url = f"https://translate.yandex.net/api/v1/tr.json/translate?{query}"
    data = _get_json(url)
    if isinstance(data, dict):
        texts = data.get("text")
        if isinstance(texts, list) and texts:
            return unescape(str(texts[0]))
    raise MtApiError(f"Unexpected Yandex response: {data!r}")


def translate_deepl_web(text: str, src_lang: str, dst_lang: str) -> str:
    """
    Use DeepL web JSON-RPC endpoint (non-official, best-effort) to avoid official API.
    """
    if not text:
        return ""
    url = "https://www2.deepl.com/jsonrpc"

    job = {
        "kind": "default",
        "raw_en_sentence": text,
        "raw_en_context_before": [],
        "raw_en_context_after": [],
        "preferred_num_beams": 1,
    }
    payload = {
        "jsonrpc": "2.0",
        "method": "LMT_handle_jobs",
        "id": random.randint(100000, 999999),
        "params": {
            "jobs": [job],
            "lang": {
                "source_lang_user_selected": src_lang.upper(),
                "target_lang": dst_lang.upper(),
            },
            "priority": 1,
            "timestamp": int(time.time() * 1000),
        },
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Origin": "https://www.deepl.com",
        "Referer": "https://www.deepl.com/translator",
    }
    response = _post_json(url, payload, headers=headers)
    if isinstance(response, dict):
        try:
            beams = response["result"]["translations"][0]["beams"]
            if beams:
                return unescape(str(beams[0]["postprocessed_sentence"]))
        except Exception as exc:  # noqa: BLE001
            raise MtApiError(f"DeepL response parse error: {exc}") from exc
    raise MtApiError(f"Unexpected DeepL response: {response!r}")


def translate_with_argos(text: str, src_lang: str, dst_lang: str) -> str:
    """Translate using argostranslate if installed and models available."""
    try:
        import argostranslate.translate  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise MtApiError("argostranslate is not installed") from exc

    try:
        return argostranslate.translate.translate(text, src_lang, dst_lang)
    except Exception as exc:  # noqa: BLE001
        raise MtApiError(f"Argos translation failed: {exc}") from exc


def translate_with_hf_model(text: str, model_name: str, src_lang: str, dst_lang: str) -> str:
    """
    Translate using a HuggingFace seq2seq model if transformers is available.

    Model name/path must be provided via settings (e.g., marian/m2m/nllb).
    """
    try:
        from transformers import pipeline  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise MtApiError("transformers is not installed") from exc

    try:
        translator = pipeline("translation", model=model_name)
        result = translator(text, src_lang=src_lang, tgt_lang=dst_lang, max_length=512)
        if isinstance(result, list) and result and "translation_text" in result[0]:
            return str(result[0]["translation_text"])
        if isinstance(result, list) and result and "generated_text" in result[0]:
            return str(result[0]["generated_text"])
        raise MtApiError(f"Unexpected transformers output: {result!r}")
    except Exception as exc:  # noqa: BLE001
        raise MtApiError(f"HuggingFace translation failed: {exc}") from exc


def summarize_prompt_data(prompt_data: Dict[str, Any]) -> str:
    """Return a compact string useful for logging prompt contents."""
    text = str(prompt_data.get("text", ""))
    src_lang = str(prompt_data.get("src_lang", ""))
    dst_lang = str(prompt_data.get("dst_lang", ""))
    title_name = prompt_data.get("title_name", "")
    characters = prompt_data.get("characters", []) or []
    terms = prompt_data.get("terms", []) or []
    recent_context = prompt_data.get("recent_context", []) or []

    return (
        f"text_len={len(text)}, src={src_lang}, dst={dst_lang}, "
        f"title={title_name!r}, characters={len(characters)}, "
        f"terms={len(terms)}, context_len={len(recent_context)}"
    )

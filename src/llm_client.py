# -*- coding: utf-8 -*-
"""LLM-клиент: любой OpenAI-совместимый /chat/completions endpoint.

Схема из Smart Lolis / kcd2-ai-npc: единый формат запроса, провайдер задаётся
config.llm.api_url + keys.llm_api_key (OpenAI, OpenRouter, Groq, Ollama,
LM Studio, любой custom).
"""
import json
import re
import urllib.error
import urllib.request

from src.config_loader import cfg, keys


class LlmError(Exception):
    pass


def normalize_chat_url(url):
    """Принимаем и базовый URL (https://api.openai.com/v1), и полный
    (.../v1/chat/completions) — как в референсах kcd2-ai-npc / Smart Lolis."""
    u = (url or "").strip().rstrip("/")
    if not u or u.endswith("/chat/completions"):
        return u
    return u + "/chat/completions"


# Значения-плейсхолдеры, которые нельзя отправлять как имя модели.
_MODEL_PLACEHOLDERS = ("", "model-name")


def _gateway_message(detail):
    """Короткая причина от шлюза из тела ошибки, например
    {"code":"INSUFFICIENT_BALANCE","message":"Insufficient account balance"}."""
    d = (detail or "").strip()
    if not d:
        return ""
    try:
        j = json.loads(d)
    except Exception:
        return d[:160].replace("\n", " ")
    if isinstance(j, dict):
        err = j.get("error")
        msg = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or j.get("code") or d
        return str(msg)[:160].replace("\n", " ")
    return d[:160].replace("\n", " ")


def chat(messages, override_max_tokens=None, override_temperature=None):
    lc = cfg.get("llm", {})
    model = (lc.get("model") or "").strip()
    if model in _MODEL_PLACEHOLDERS:
        raise LlmError(u"не выбрана модель — открой настройки, нажми «🔍 Модели» "
                       u"или впиши имя модели вручную")
    url = normalize_chat_url(lc.get("api_url", "https://api.openai.com/v1"))
    if not url:
        raise LlmError(u"не указан API URL провайдера (настройки мода)")
    provider = (lc.get("provider") or "").strip().lower()
    key_by_provider = {
        "groq": "groq_api_key",
        "mistral": "mistral_api_key",
        "openrouter": "llm_api_key",
        "openai": "openai_api_key",
        "vsegpt": "vsegpt_api_key",
        "proxyapi": "proxyapi_api_key",
        "nvidia": "nvidia_api_key",
        "cohere": "cohere_api_key",
        "github": "github_api_key",
        "custom": "custom_llm_api_key",
    }
    named = key_by_provider.get(provider, "")
    api_key = (keys.get(named, "") if named else "") or keys.get("custom_llm_api_key", "") or keys.get("llm_api_key", "") or keys.get("openai_api_key", "")
    timeout = int(lc.get("request_timeout", 90))

    body = {
        "model": model,
        "messages": messages,
        "max_tokens": int(override_max_tokens or lc.get("max_tokens", 400)),
        "temperature": float(override_temperature if override_temperature is not None else lc.get("temperature", 0.9)),
    }
    headers = {"Content-Type": "application/json", "User-Agent": "ES-AI-Mod/1.0"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        friendly = {
            401: u"неверный API-ключ (проверь его в настройках мода)",
            403: u"доступ запрещён — регион или неверный ключ",
            404: u"нет такого URL/модели",
            429: u"превышен лимит запросов, попробуй позже",
            500: u"ошибка на стороне провайдера",
            503: u"провайдер временно недоступен",
        }
        if e.code in friendly:
            g = _gateway_message(detail)
            if g and e.code in (401, 403, 404):
                raise LlmError(u"%s (HTTP %s): %s" % (friendly[e.code], e.code, g))
            raise LlmError(u"%s (HTTP %s)" % (friendly[e.code], e.code))
        raise LlmError(u"HTTP %s: %s" % (e.code, detail))
    except Exception as e:
        raise LlmError("Нет связи с LLM (%s): %s" % (url, e))

    try:
        text = payload["choices"][0]["message"]["content"]
    except Exception:
        raise LlmError("Странный ответ LLM: %s" % json.dumps(payload, ensure_ascii=False)[:400])
    return text or ""


_RE_AI_WORDS = re.compile(
    r"\b(?:искусственн\w+ интеллект\w*|языков\w+ модел\w+|нейросет\w+|нейронн\w+ сет\w+|"
    r"artificial intelligence|language model|neural network|large language model)\b",
    re.IGNORECASE,
)


def sanitize_in_character(text):
    """Правка из AI_lena: вырезаем проговорки про ИИ."""
    return _RE_AI_WORDS.sub("житель Совёнка", text or "")


def strip_prompt_leak(text, sys_text):
    """Убирает из ответа строки, процитированные дословно из промпта
    (слабые модели иногда начинают первый ответ эхом системного промпта)."""
    if not text or not sys_text:
        return text
    out = []
    for line in text.split("\n"):
        l = line.strip()
        if len(l) > 30 and l in sys_text:
            continue
        out.append(line)
    return "\n".join(out).strip()


def quick_summarize(text):
    """Дешёвый вызов для сжатия памяти."""
    return chat([
        {"role": "system", "content": (
            "Сожми переписку в память для следующего разговора. По-русски, 4-8 предложений: "
            "кто участвовал, о чём говорили, что обещали, какой тон и отношения. Без цитат и без воды."
        )},
        {"role": "user", "content": text[:6000]},
    ], override_max_tokens=280, override_temperature=0.2)

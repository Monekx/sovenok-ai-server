# -*- coding: utf-8 -*-
"""TTS-слой по схеме Smart Lolis (ElevenLabsTtsService.cs): провайдер-свитч.

Провайдеры:
  auto        — первый доступный: elevenlabs (если ключ) -> edge-tts -> sapi -> custom
  elevenlabs  — POST https://api.elevenlabs.io/v1/text-to-speech/{voice}
  openai      — POST https://api.openai.com/v1/audio/speech
  edge        — бесплатный Microsoft edge-tts (pip install edge-tts)
  sapi        — локальный Windows SAPI (pip install pyttsx3), без интернета
  custom      — OpenAI-совместимый /audio/speech по custom_tts_url
  off         — синтез выключен

Результат — путь к готовому аудиофайлу (mp3/wav) в cache_dir.
"""
import base64
import json
import os
import tempfile
import time
import urllib.error
import urllib.request

from src.config_loader import cfg, keys

_cache_state = {}


def _cache_dir():
    d = cfg.get("tts", {}).get("cache_dir", "cache_tts")
    if not os.path.isabs(d):
        from config_loader import user_data_dir
        d = os.path.join(user_data_dir(), d)
    os.makedirs(d, exist_ok=True)
    return d


def available_providers():
    """Что реально доступно на этой машине."""
    av = {}
    av["elevenlabs"] = bool(keys.get("elevenlabs_api_key"))
    av["fish"] = bool(keys.get("fish_api_key"))
    try:
        import edge_tts  # noqa
        av["edge"] = True
    except Exception:
        av["edge"] = False
    try:
        import pyttsx3  # noqa
        av["sapi"] = True
    except Exception:
        av["sapi"] = False
    av["openai"] = bool(keys.get("openai_api_key"))
    av["custom"] = bool(cfg.get("tts", {}).get("custom_tts_url"))
    return av


def resolve_provider():
    pref = cfg.get("tts", {}).get("provider", "auto")
    av = available_providers()
    if pref != "auto":
        if av.get(pref):
            return pref
        return None
    for p in ("elevenlabs", "fish", "edge", "sapi", "openai", "custom"):
        if av.get(p):
            return p
    return None


_FISH_MODEL = "s2.1-pro-free"
_FISH_VOICE = "6dc11f3f67a543f6ad4537a4a347e224"
_EDGE_FEMALE = "ru-RU-SvetlanaNeural"
_EDGE_MALE = "ru-RU-DmitryNeural"
_MALE_IDS = {"el", "sh", "pi"}


def _is_male(ch):
    """Парни лагеря (Шурик, Электроник) — мужской голос, остальные — женский."""
    if not ch:
        return False
    g = str(ch.get("gender") or "").strip().lower()
    if g in ("m", "male", "м", "муж"):
        return True
    if g in ("f", "female", "ж", "жен"):
        return False
    return (ch.get("id") or "") in _MALE_IDS


def _first(*vals):
    for v in vals:
        if v:
            return v
    return ""


def _gender_pair(provider):
    """Женский и мужской голос провайдера. Пустой мужской падает на женский."""
    tts = cfg.get("tts", {}) or {}
    if provider == "elevenlabs":
        female = _first(tts.get("elevenlabs_voice_female"), tts.get("elevenlabs_default_voice"))
        male = _first(tts.get("elevenlabs_voice_male"))
    elif provider == "fish":
        female = _first(tts.get("fish_voice_female"), tts.get("fish_reference_id"), _FISH_VOICE)
        male = _first(tts.get("fish_voice_male"))
    elif provider == "edge":
        female = _first(tts.get("edge_voice_female"), tts.get("edge_voice"), _EDGE_FEMALE)
        male = _first(tts.get("edge_voice_male"), _EDGE_MALE)
    elif provider == "openai":
        female = _first(tts.get("openai_voice_female"), tts.get("openai_default_voice"), "nova")
        male = _first(tts.get("openai_voice_male"), "onyx")
    elif provider == "custom":
        female = _first(tts.get("custom_voice_female"), "nova")
        male = _first(tts.get("custom_voice_male"), "onyx")
    elif provider == "sapi":
        female = _first(tts.get("sapi_voice_female"), tts.get("sapi_voice"))
        male = _first(tts.get("sapi_voice_male"))
    else:
        female, male = "", ""
    return female, male or female


def _pick_gender(ch, provider, narrator=False):
    female, male = _gender_pair(provider)
    if narrator or not _is_male(ch):
        return female
    return male or female


def _voice_for(ch, provider):
    return _pick_gender(ch, provider, narrator=False)


def _narrator_voice(provider):
    return _pick_gender(None, provider, narrator=True)


def synthesize(text, character=None, narrator=False):
    """Возвращает (path, provider) или (None, error_reason)."""
    provider = resolve_provider()
    if not provider:
        return None, "tts_disabled"
    text = (text or "").strip()
    if not text:
        return None, "empty"
    # Не озвучиваем служебную конструкцию эмоций, если она проскочила
    if text.startswith("(") and ")" in text[:20]:
        text = text[text.index(")") + 1:].strip()

    out = os.path.join(_cache_dir(), "tts_%d.mp3" % int(time.time() * 1000 % 100000000))
    if provider == "sapi":
        out = os.path.splitext(out)[0] + ".wav"

    try:
        if provider == "fish":
            ref = _narrator_voice("fish") if narrator else _voice_for(character, "fish")
            _fish(text, ref, cfg.get("tts", {}).get("fish_model") or _FISH_MODEL, out)
        elif provider == "elevenlabs":
            _elevenlabs(text, _voice_for(character, provider) if not narrator else _narrator_voice(provider), out)
        elif provider == "openai":
            _openai(text, _voice_for(character, provider) if not narrator else _narrator_voice(provider), out)
        elif provider == "custom":
            _openai_compatible(text, _voice_for(character, provider) if not narrator else _narrator_voice(provider), out)
        elif provider == "edge":
            _edge.note = ""
            _edge(text, _voice_for(character, provider) if not narrator else _narrator_voice(provider), out)
        elif provider == "sapi":
            _sapi(text, out, _narrator_voice("sapi") if narrator else _voice_for(character, "sapi"))
        else:
            return None, "unknown_provider"
    except Exception as e:
        try:
            os.remove(out)
        except Exception:
            pass
        return None, "%s: %s" % (provider, e)

    # Чистим старые файлы, оставляем последние 20
    try:
        files = sorted([os.path.join(_cache_dir(), f) for f in os.listdir(_cache_dir())],
                       key=os.path.getmtime)
        for old in files[:-20]:
            os.remove(old)
    except Exception:
        pass
    if provider == "edge" and getattr(_edge, "note", ""):
        return out, u"edge · %s" % _edge.note
    if provider == "edge" and getattr(_edge, "used", ""):
        return out, u"edge · %s" % _edge.used
    return out, provider


def _http_json(url, body, headers):
    headers = dict(headers)
    headers.setdefault("User-Agent", "ES-AI-Mod/1.0")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _fish(text, reference_id, model, out):
    """Fish Audio: POST /v1/tts (схема из Smart Lolis: Bearer + reference_id)."""
    url = "https://api.fish.audio/v1/tts"
    headers = {
        "Authorization": "Bearer " + keys.get("fish_api_key", ""),
        "Content-Type": "application/json",
        "model": model or _FISH_MODEL,
    }
    body = {"text": text, "format": "mp3"}
    if reference_id:
        body["reference_id"] = reference_id
    audio = _http_json(url, body, headers)
    with open(out, "wb") as f:
        f.write(audio)


def _elevenlabs(text, voice, out):
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s" % voice
    body = {
        "text": text,
        "model_id": cfg.get("tts", {}).get("elevenlabs_model", "eleven_multilingual_v2"),
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
    }
    headers = {
        "xi-api-key": keys.get("elevenlabs_api_key", ""),
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    audio = _http_json(url, body, headers)
    with open(out, "wb") as f:
        f.write(audio)


def _openai(text, voice, out):
    url = "https://api.openai.com/v1/audio/speech"
    body = {"model": cfg.get("tts", {}).get("openai_tts_model", "tts-1"), "input": text,
            "voice": voice, "response_format": "mp3"}
    headers = {"Authorization": "Bearer " + keys.get("openai_api_key", ""),
               "Content-Type": "application/json"}
    audio = _http_json(url, body, headers)
    with open(out, "wb") as f:
        f.write(audio)


def _openai_compatible(text, voice, out):
    url = cfg.get("tts", {}).get("custom_tts_url")
    body = {"model": cfg.get("tts", {}).get("custom_tts_model", "tts-1"),
            "input": text, "voice": voice, "response_format": "mp3"}
    headers = {"Content-Type": "application/json"}
    k = keys.get("custom_tts_api_key", "")
    if k:
        headers["Authorization"] = "Bearer " + k
    audio = _http_json(url, body, headers)
    with open(out, "wb") as f:
        f.write(audio)


def _clean_edge_voice(voice):
    """Из поля могла приехать подпись «ru-RU-DmitryNeural · Male» — оставляем ShortName."""
    voice = (voice or "").replace(u"\u00b7", " ").strip().strip("\"'")
    for part in voice.split():
        if part.endswith("Neural") and "-" in part:
            return part
    return voice or _EDGE_FEMALE


def _edge_version():
    try:
        import edge_tts
        return getattr(edge_tts, "__version__", "?")
    except Exception:
        return "?"


def _edge_log(msg):
    try:
        from config_loader import user_data_dir
        path = os.path.join(user_data_dir(), "tts_edge.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _edge_once(text, voice, out):
    """Один запрос к edge-tts. Пустой mp3 — тоже ошибка."""
    import asyncio
    import edge_tts
    if os.path.exists(out):
        try:
            os.remove(out)
        except Exception:
            pass

    async def run():
        tts = edge_tts.Communicate(text, voice, rate="+0%", volume="+0%", pitch="+0Hz")
        await tts.save(out)

    asyncio.run(run())
    if not os.path.exists(out) or os.path.getsize(out) < 200:
        raise RuntimeError("пустой файл")


def _edge_subprocess(text, voice, out):
    """Свежий процесс: в окне настроек повторный asyncio.run иногда возвращает пустой звук."""
    import subprocess
    import sys
    if os.path.exists(out):
        try:
            os.remove(out)
        except Exception:
            pass
    script = (
        "import asyncio,sys,edge_tts\n"
        "async def main():\n"
        "    c=edge_tts.Communicate(sys.argv[1], sys.argv[2], rate='+0%', volume='+0%', pitch='+0Hz')\n"
        "    await c.save(sys.argv[3])\n"
        "asyncio.run(main())\n"
    )
    flags = 0x08000000 if os.name == "nt" else 0
    proc = subprocess.run(
        [sys.executable, "-c", script, text, voice, out],
        capture_output=True, timeout=50, creationflags=flags,
    )
    err = ((proc.stderr or b"") + (proc.stdout or b"")).decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(err[-240:] or ("код %s" % proc.returncode))
    if not os.path.exists(out) or os.path.getsize(out) < 200:
        raise RuntimeError(err[-240:] or "пустой файл")


_EDGE_MALE_FALLBACKS = (
    "en-US-AndrewMultilingualNeural",
    "de-DE-FlorianMultilingualNeural",
)


def _edge(text, voice, out):
    """Пишет mp3. Возвращает ShortName, которым реально озвучили."""
    voice = _clean_edge_voice(voice)
    ver = _edge_version()
    attempts = [voice, voice]
    # Старые библиотеки иногда принимают только длинное имя Microsoft.
    if voice.startswith("ru-RU-") and voice.endswith("Neural"):
        short = voice[len("ru-RU-"):]
        attempts.append("Microsoft Server Speech Text to Speech Voice (ru-RU, %s)" % short)
    if "Dmitry" in voice:
        attempts.extend(_EDGE_MALE_FALLBACKS)
    last = None
    for i, candidate in enumerate(attempts):
        try:
            if i == 0:
                _edge_once(text, candidate, out)
            else:
                _edge_subprocess(text, candidate, out)
            _edge.used = candidate if candidate.startswith("ru-") or candidate.startswith("en-") or candidate.startswith("de-") else voice
            _edge.note = ""
            if _edge.used != voice:
                _edge.note = u"Дмитрий не ответил, взял %s" % _edge.used
                _edge_log("fallback %s -> %s (%s)" % (voice, _edge.used, last))
            else:
                _edge_log("ok %s edge-tts %s" % (voice, ver))
            return _edge.used
        except Exception as e:
            last = e
            _edge_log("fail %s edge-tts %s: %s" % (candidate, ver, e))
            time.sleep(0.35)
    raise RuntimeError(u"%s не вернул звук (%s; edge-tts %s)" % (voice, last, ver))


def _sapi(text, out, voice=""):
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    if voice:
        try:
            engine.setProperty("voice", voice)
        except Exception:
            pass
    engine.save_to_file(text, out)
    engine.runAndWait()

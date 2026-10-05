# -*- coding: utf-8 -*-
"""ES AI Server — внешний сервер AI-мода для «Бесконечного лета».

Схема (как в kcd2-ai-npc и Smart Lolis):
    игра (Ren'Py, Python 2.7) --HTTP localhost--> этот сервер (Python 3)
        -> LLM (любой OpenAI-совместимый API)
        -> TTS (ElevenLabs / OpenAI / edge-tts / SAPI)
        -> STT (Groq Whisper / OpenAI Whisper / локальный faster-whisper)

Запуск:  python main.py            (порт и всё остальное — в config.json)
Проверка: python main.py --check
"""
import json
import os
import re
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config_loader
from config_loader import cfg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_EMOTION_RE = re.compile(r"^\(([^)]{1,30})\)\s*(.*)$", re.DOTALL)
_ACTION_GOTO_RE = re.compile(r"\s*\[(?:action:)?(?:goto|локация|место)[:\s]+([^\]]+)\]", re.IGNORECASE)
_ACTION_TIME_RE = re.compile(r"\s*\[(?:action:)?(?:time|время)[:\s]+([^\]]+)\]", re.IGNORECASE)
_ACTION_DRESS_RE = re.compile(r"\s*\[(?:action:)?(?:dress|одежда|наряд)[:\s]+([^\]]+)\]", re.IGNORECASE)

# Слова -> канонический сигнал наряда для клиента: swim / cover / sport.
_DRESS_SWIM = ("swim", "купальник", "купаться", "искупаться", "загорать", "плаваем")
_DRESS_COVER = ("cover", "форма", "форму", "одеть", "оденься", "пионер", "pioneer", "normal", "прикры")
_DRESS_SPORT = ("sport", "спорт")


def normalize_dress(value):
    """Значение тега [action:dress:...] -> 'swim' | 'cover' | 'sport' | None."""
    t = (value or "").strip().lower()
    if not t:
        return None
    if any(w in t for w in _DRESS_SWIM):
        return "swim"
    if any(w in t for w in _DRESS_SPORT):
        return "sport"
    if any(w in t for w in _DRESS_COVER):
        return "cover"
    return None


_LOCATION_ALIASES = [
    # раздел 28 (продолжение): контекстные подлокации — специфичные фразы РАНЬШЕ общих.
    ("semen_room", ("комната семёна", "комнату семёна", "комнате семёна",
                    "в свою комнату", "к себе в комнату", "в мою комнату")),
    ("bus_stop", ("автобусная остановка", "остановка автобуса", "на остановк", "к остановке")),
    ("bathhouse", ("в баню", "из бани", "в бане", "баня")),
    ("musclub_inside", ("внутрь музклуба", "внутри музклуба", "внутрь музыкального клуба",
                        "внутри музыкального клуба")),
    ("dining_ext", ("у столовой", "возле столовой", "около столовой",
                    "перед столовой", "снаружи столовой")),
    ("stage_big", ("большая сцена", "большой сцене", "к большой сцене",
                   "на концерт", "концертная сцена")),
    ("gate_no_bus", ("автобус уехал", "автобуса уже нет", "ворота без автобуса")),
    ("dv_house_ext", ("у домика алисы", "возле домика алисы", "перед домиком алисы",
                      "у домика ульяны", "возле домика ульяны")),
    ("mt_house_ext", ("у домика вожатой", "возле домика вожатой",
                      "перед домиком вожатой", "снаружи домика вожатой")),
    ("sl_house_ext", ("у домика слави", "возле домика слави",
                      "у домика жени", "перед домиком слави")),
    ("un_house_ext", ("у домика лены", "возле домика лены",
                      "у домика мику", "перед домиком лены")),
    ("bus_gate", ("автобус у ворот", "к автобусу", "возле автобуса")),
    ("bus_inside", ("в автобус", "внутрь автобуса", "салон автобуса")),
    ("mt_room", ("комната вожатой", "комнату вожатой", "домик вожатой", "к ольге дмитриевне")),
    ("aidpost_inside", ("внутрь медпункта", "в медпункт", "кабинет виолы")),
    ("club_room", ("в клуб кибернетиков", "внутрь клуба", "к кибернетикам")),
    ("dv_room", ("домик алисы", "комната алисы", "домик ульяны", "комната ульяны")),
    ("sl_room", ("домик слави", "комната слави", "домик жени", "комната жени")),
    ("un_room", ("домик лены", "комната лены", "домик мику", "комната мику")),
    ("camp_gate", ("ворота лагеря", "к воротам", "вход в лагерь")),
    ("old_building", ("старый корпус", "старое здание", "заброшенный корпус")),
    ("catacombs", ("катакомб", "подземель")),
    ("mine", ("в шахту", "заброшенная шахта", "в рудник")),
    ("boathouse", ("лодочная станция", "к лодкам", "на причал")),
    ("washstand", ("умывальник", "умыться")),
    ("road", ("дорога к лагерю", "на дорогу", "по дороге")),
    ("houses", ("аллея домиков", "жилые домики", "между домиками")),
    ("aidpost", ("к медпункту", "возле медпункта")),
    ("clubs", ("к клубам", "возле клубов", "здание кружков")),
    ("beach", ("пляж", "купаться", "искупаться", "плавать", "реке", "реку", "воде", "пруд")),
    ("island", ("остров", "острове")),
    ("polyana", ("полян",)),
    ("path", ("троп", "по лесу", "лесу", "лес")),
    ("playground", ("спортплощадк", "волейбол")),
    ("musclub", ("музклуб", "музыкальн")),
    ("stage", ("на сцен", "к сцен")),
    ("dining", ("столов", "поесть", "пообедать", "поужинать", "компот")),
    ("library", ("библиотек", "почитать", "книг")),
    ("square", ("на площад", "к площад", "по лагерю")),
]


def detect_location_in_text(text):
    t = (text or "").lower()
    if not t:
        return None
    for loc_id, words in _LOCATION_ALIASES:
        for w in words:
            if w in t:
                return loc_id
    return None


def normalize_location(value):
    """Привести ID/русское название из action-тега к каноническому ID."""
    t = (value or "").strip().lower()
    if not t:
        return None
    for loc_id, words in _LOCATION_ALIASES:
        if t == loc_id:
            return loc_id
        for word in words:
            if word in t or t in word:
                return loc_id
    return None



def parse_action_tags(raw):
    """Вытаскивает [action:goto:...], [action:time:...] и [action:dress:...],
    возвращает (чистый_текст, goto, time, dress)."""
    goto = time = dress = None
    m = _ACTION_GOTO_RE.search(raw)
    if m:
        goto = m.group(1).strip().lower()
        raw = _ACTION_GOTO_RE.sub(" ", raw)
    m = _ACTION_TIME_RE.search(raw)
    if m:
        time = m.group(1).strip().lower()
        raw = _ACTION_TIME_RE.sub(" ", raw)
    m = _ACTION_DRESS_RE.search(raw)
    if m:
        dress = normalize_dress(m.group(1))
        raw = _ACTION_DRESS_RE.sub(" ", raw)
    return re.sub(r"\s{2,}", " ", raw).strip(), goto, time, dress


# ---------------------------------------------------------------- endpoints ---

def health():
    import tts_client
    import stt_client
    from characters_store import characters
    from config_loader import keys
    llm_cfg = cfg.get("llm", {})
    return {
        "ok": True,
        "server": "es-ai-server/1.0",
        "llm": {
            "url": llm_cfg.get("api_url", ""),
            "model": llm_cfg.get("model", ""),
            "key_present": bool(keys.get("llm_api_key") or keys.get("openai_api_key")),
        },
        "tts": {
            "provider": tts_client.resolve_provider(),
            "available": tts_client.available_providers(),
        },
        "stt": {
            "transcriber": stt_client.resolve_transcriber(),
            "mic": stt_client.available_providers().get("record", False),
            "available": stt_client.available_providers(),
        },
        "characters": [{"id": c["id"], "name": c["name"], "color": c.get("color", "")}
                       for c in characters()],
    }


def chat(payload):
    import conversation
    import llm_client
    from characters_store import get_character, map_emotion

    char_id = payload.get("character") or "un"
    text = (payload.get("text") or "").strip()
    novel_context = payload.get("novel_context") or []
    speaker = payload.get("speaker") or ""
    location = (payload.get("location") or "").strip()
    if not text:
        return {"ok": False, "error": "Пустой запрос"}

    messages = conversation.build_history_block(char_id, cfg, novel_context, speaker,
                                                location=location)
    # КРИТИЧНО: build_history_block содержит только прошлую историю. Текущее
    # сообщение нужно добавить до вызова LLM, иначе ответы запаздывают на один шаг.
    messages.append({"role": "user", "content": text})

    def generate_and_parse(call_messages):
        raw_text = llm_client.chat(call_messages)
        raw_text = llm_client.sanitize_in_character(raw_text).strip()
        raw_text = llm_client.strip_prompt_leak(raw_text, messages[0]["content"])
        match = _EMOTION_RE.match(raw_text)
        if match:
            emo = match.group(1).strip().lower()
            answer = match.group(2).strip()
        else:
            emo, answer = "нормально", raw_text
        answer = answer.strip().strip('"').strip()
        answer, action_goto, action_time, action_dress = parse_action_tags(answer)
        return emo, answer, action_goto, action_time, action_dress

    try:
        emotion_raw, reply, goto, time_tag, dress_tag = generate_and_parse(messages)
        if not reply:
            retry_messages = list(messages)
            retry_messages.append({
                "role": "system",
                "content": "Предыдущая генерация оказалась пустой. Обязательно дай Семёну "
                           "содержательный ответ из 1-3 предложений, затем при необходимости action-тег."
            })
            emotion_raw, reply, goto, time_tag, dress_tag = generate_and_parse(retry_messages)
    except Exception as e:
        return {"ok": False, "error": "LLM: %s" % e}

    # Даже при втором пустом ответе не оставляем игру без реплики.
    if not reply:
        emotion_raw = "нормально"
        reply = "Я тебя слышу, Семён. Давай продолжим."
    goto = normalize_location(goto) if goto else detect_location_in_text(text)
    emotion = map_emotion(char_id, emotion_raw)

    conversation.add_exchange(char_id, text, reply)
    threading.Thread(target=conversation.maybe_compress, daemon=True,
                     args=(char_id, cfg, llm_client.quick_summarize)).start()

    ch = get_character(char_id)
    out = {"ok": True, "reply": reply, "emotion": emotion, "name": ch["name"], "id": ch["id"]}
    if goto:
        out["goto"] = goto
    if time_tag:
        out["time"] = time_tag
    if dress_tag:
        out["dress"] = dress_tag
    return out


def initiative(payload):
    import conversation
    import llm_client
    from characters_store import get_character, map_emotion, player_block

    char_id = payload.get("character") or "un"
    novel_context = payload.get("novel_context") or []
    location = (payload.get("location") or "").strip()
    ch = get_character(char_id)

    hist, summary = conversation.get_history(char_id)
    tail = hist[-6:]

    sys_text = ch["persona"] + "\n\n" + (
        "Ты решила(а) сама заговорить с Семёном: он давно молчит. Скажи что-нибудь сама — "
        "вопрос, реплику, приглашение погулять. 1-2 коротких предложения. "
        "Как обычно, начни с эмоции в скобках.")
    if location:
        sys_text += "\n\nТекущее место действия (где вы сейчас): " + location + ". Не противоречь этой локации."
    if summary:
        sys_text += "\n\nПамять о прошлых разговорах:\n" + summary
    if novel_context:
        lines = ["%s: %s" % ((i.get("who") or "..."), (i.get("what") or "").strip())
                 for i in novel_context[-8:] if (i.get("what") or "").strip()]
        if lines:
            sys_text += "\n\nПоследние события:\n" + "\n".join(lines)
    pb = player_block()
    if pb:
        sys_text += "\n\n" + pb

    messages = [{"role": "system", "content": sys_text}] + tail + \
               [{"role": "user", "content": "(Семён молчит уже давно. Заговори первой.)"}]
    try:
        raw = llm_client.chat(messages, override_max_tokens=120)
    except Exception as e:
        return {"ok": False, "error": "LLM: %s" % e}
    raw = llm_client.sanitize_in_character(raw).strip()
    raw = llm_client.strip_prompt_leak(raw, sys_text)

    m = _EMOTION_RE.match(raw)
    if m:
        emotion_raw, reply = m.group(1).strip().lower(), m.group(2).strip()
    else:
        emotion_raw, reply = "нормально", raw
    reply = reply.strip().strip('"').strip()
    reply, goto, time_tag, dress_tag = parse_action_tags(reply)
    goto = normalize_location(goto)
    out = {"ok": True, "reply": reply, "emotion": map_emotion(char_id, emotion_raw),
           "name": ch["name"], "id": ch["id"]}
    if goto:
        out["goto"] = goto
    if time_tag:
        out["time"] = time_tag
    if dress_tag:
        out["dress"] = dress_tag
    return out


def cameo(payload):
    """Реплика персонажа, который неожиданно застаёт сцену (камео)."""
    import llm_client
    from characters_store import get_character, map_emotion

    cid = payload.get("character") or "mt"
    active = (payload.get("active") or "одной из девушек").strip()
    location = (payload.get("location") or "").strip()
    romantic = bool(payload.get("romantic"))
    ch = get_character(cid)

    sit = "Ты неожиданно заходишь (или подходишь) и застаёшь Семёна наедине с %s." % active
    if location:
        sit += " Место: " + location + "."
    if romantic:
        sit += (" Похоже, у них романтический, интимный момент — ты застаёшь их врасплох. "
                "Отреагируй так, как это свойственно ТВОЕМУ характеру: удивление, смущение, "
                "ревность, строгость, подколка или спокойствие.")
    else:
        sit += " Просто отреагируй на встречу в своей манере."
    sit += (" Дай РОВНО одну короткую реплику (1-2 предложения), прямую речь без описания действий. "
            "Начни с эмоции в скобках, как обычно. Тегов [action:...] не используй.")

    messages = [
        {"role": "system", "content": ch["persona"] + "\n\n" + ch.get("speech", "") + "\n\n" + sit},
        {"role": "user", "content": "(Ты открываешь дверь / подходишь и видишь их.)"},
    ]
    try:
        raw = llm_client.chat(messages, override_max_tokens=100)
    except Exception as e:
        return {"ok": False, "error": "LLM: %s" % e}
    raw = llm_client.sanitize_in_character(raw).strip()

    m = _EMOTION_RE.match(raw)
    if m:
        emo_raw, reply = m.group(1).strip().lower(), m.group(2).strip()
    else:
        emo_raw, reply = ("удивление" if not romantic else "шок"), raw
    reply, _g, _t, _d = parse_action_tags(reply)
    reply = reply.strip().strip('"').strip()
    if not reply:
        return {"ok": False, "error": "empty"}
    return {"ok": True, "reply": reply, "emotion": map_emotion(cid, emo_raw),
            "name": ch["name"], "id": cid}


def tts(payload):
    import tts_client
    from characters_store import get_character
    text = payload.get("text") or ""
    narrator = bool(payload.get("narrator"))
    ch = None if narrator else get_character(payload.get("character") or "un")
    path, info = tts_client.synthesize(text, ch, narrator)
    if not path:
        return {"ok": False, "error": info}
    return {"ok": True, "path": os.path.abspath(path), "provider": info}


def stt_record(payload):
    import stt_client
    pref = (payload.get("provider") or cfg.get("stt", {}).get("provider") or "auto")
    if pref == "winh":
        try:
            text = stt_client.dictate_windows(max_seconds=float(payload.get("max_seconds") or 18))
        except Exception as e:
            return {"ok": False, "error": "winh: %s" % e}
        return {"ok": True, "text": text or "", "provider": "winh"}
    wav = stt_client.record_audio(max_seconds=payload.get("max_seconds"))
    if not wav:
        return {"ok": False, "error": "no_audio"}
    text, info = stt_client.transcribe(wav)
    if text is None:
        return {"ok": False, "error": info}
    return {"ok": True, "text": text, "provider": info}


def open_settings_ui():
    """Открыть нативное окно настроек (отдельный процесс без консоли)."""
    import subprocess
    win = os.path.join(BASE_DIR, "settings.pyw")
    if not os.path.exists(win):
        return {"ok": False, "error": "settings.pyw не найден рядом с сервером"}
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    # cwd=temp: окно не держит папку сервера, чтобы установщик мог обновлять файлы
    import tempfile
    subprocess.Popen([sys.executable, win], cwd=tempfile.gettempdir(), creationflags=flags)
    return {"ok": True}


def history_clear(payload):
    import conversation
    char_id = payload.get("character")
    if char_id:
        conversation.clear(char_id)
        return {"ok": True, "cleared": char_id}
    from characters_store import characters
    for c in characters():
        conversation.clear(c["id"])
    return {"ok": True, "cleared": "all"}


def history_get(char_id):
    import conversation
    from characters_store import characters, get_character
    if not char_id:
        items = []
        for c in characters():
            msgs, summary = conversation.get_history(c["id"])
            items.append({"id": c["id"], "name": c["name"], "count": len(msgs),
                          "has_summary": bool(summary)})
        return {"ok": True, "characters": items}
    msgs, summary = conversation.get_history(char_id)
    ch = get_character(char_id)
    return {"ok": True, "id": char_id, "name": ch.get("name") or char_id,
            "messages": msgs, "summary": summary or ""}


def history_set_summary(payload):
    import conversation
    char_id = payload.get("character") or ""
    if not char_id:
        return {"ok": False, "error": "нет персонажа"}
    summary = conversation.set_summary(char_id, payload.get("summary") or "")
    return {"ok": True, "id": char_id, "summary": summary}


def history_compress(payload):
    import conversation
    import llm_client
    char_id = payload.get("character") or ""
    if not char_id:
        return {"ok": False, "error": "нет персонажа"}
    ok = conversation.maybe_compress(char_id, cfg, llm_client.quick_summarize, force=True)
    _msgs, summary = conversation.get_history(char_id)
    if not ok and not summary:
        return {"ok": False, "error": "нечего сжимать или LLM не ответила"}
    return {"ok": True, "id": char_id, "summary": summary, "updated": bool(ok)}


def reload_config():
    import characters_store
    config_loader.reload_all()
    characters_store.reload()
    return {"ok": True}


# ------------------------------------------------------- config UI (мод) ---

_CFG_SECTIONS = {
    "llm": {"provider", "api_url", "model", "max_tokens", "temperature", "request_timeout"},
    "tts": {"provider", "elevenlabs_default_voice", "openai_tts_model", "custom_tts_url", "cache_dir"},
    "stt": {"provider", "language", "max_record_seconds"},
}

_KEY_NAMES = ("llm_api_key", "groq_api_key", "mistral_api_key", "elevenlabs_api_key", "openai_api_key", "custom_tts_api_key", "custom_llm_api_key", "vsegpt_api_key", "proxyapi_api_key", "nvidia_api_key", "cohere_api_key", "github_api_key")

# Базовые URL (как в kcd2-ai-npc): /chat/completions дописывает llm_client.normalize_chat_url,
# так что пользователь может вписать и базу, и полный путь.
_LLM_PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "vsegpt": ("https://api.vsegpt.ru/v1", ""),
    "proxyapi": ("https://api.proxyapi.ru/openai/v1", "gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1", "llama3.1:8b"),
    "lmstudio": ("http://localhost:1234/v1", "local-model"),
    "custom": ("http://127.0.0.1:8080/v1", ""),
}


def _mask_key(value):
    value = value or ""
    return {"present": bool(value), "tail": (value[-4:] if len(value) >= 4 else ("*" * len(value) if value else ""))}


def get_config_state():
    import tts_client
    import stt_client
    from config_loader import keys
    lc = cfg.get("llm", {})
    tc = cfg.get("tts", {})
    sc = cfg.get("stt", {})
    return {
        "ok": True,
        "config": {
            "llm": {
                "provider": lc.get("provider", "groq"),
                "api_url": lc.get("api_url", ""),
                "model": lc.get("model", ""),
                "max_tokens": lc.get("max_tokens", 400),
                "temperature": lc.get("temperature", 0.9),
            },
            "tts": {
                "provider": tc.get("provider", "auto"),
                "elevenlabs_default_voice": tc.get("elevenlabs_default_voice", ""),
                "openai_tts_model": tc.get("openai_tts_model", ""),
                "custom_tts_url": tc.get("custom_tts_url", ""),
            },
            "stt": {
                "provider": sc.get("provider", "auto"),
                "language": sc.get("language", "ru"),
            },
            "cameo_enabled": cfg.get("cameo_enabled", True),
        },
        "keys": {name: _mask_key(keys.get(name, "")) for name in _KEY_NAMES},
        "tts_available": tts_client.available_providers(),
        "stt_available": stt_client.available_providers(),
        "presets": {k: {"api_url": v[0], "model": v[1]} for k, v in _LLM_PRESETS.items()},
    }


def config_set(payload):
    section = payload.get("section", "")
    key = payload.get("key", "")
    value = payload.get("value")
    if section not in _CFG_SECTIONS or key not in _CFG_SECTIONS[section]:
        return {"ok": False, "error": "недопустимый параметр %s.%s" % (section, key)}
    if section not in cfg or not isinstance(cfg[section], dict):
        cfg[section] = {}
    if isinstance(value, str):
        value = value.strip()
    if key in ("max_tokens", "request_timeout"):
        value = int(value)
    elif key == "temperature":
        value = float(value)
    cfg[section][key] = value
    config_loader.save_config()
    return {"ok": True}


def keys_set(payload):
    from config_loader import keys, save_keys
    name = payload.get("name", "")
    value = payload.get("value")
    if name not in _KEY_NAMES:
        return {"ok": False, "error": "недопустимое имя ключа"}
    if value is None:
        keys[name] = ""  # очистка
    else:
        value = str(value).strip()
        if not value:
            return {"ok": False, "error": "пустой ключ (чтобы очистить, передай null)"}
        keys[name] = value
    save_keys()
    return {"ok": True, "masked": _mask_key(keys.get(name, ""))}


def test_llm():
    import time as _t
    import llm_client
    t0 = _t.time()
    try:
        txt = llm_client.chat(
            [{"role": "system", "content": "Проверка связи. Ответь ровно одним словом: связь"},
             {"role": "user", "content": "ping"}],
            override_max_tokens=20, override_temperature=0.2)
        return {"ok": True, "latency_ms": int((_t.time() - t0) * 1000),
                "preview": (txt or "").strip()[:120]}
    except Exception as e:
        return {"ok": False, "latency_ms": int((_t.time() - t0) * 1000), "error": str(e)}


def test_tts(payload):
    import tts_client
    from characters_store import get_character
    ch = get_character(payload.get("character") or "un")
    text = "Привет, Семён! Проверка голоса."
    path, info = tts_client.synthesize(text, ch, False)
    if not path:
        return {"ok": False, "error": info}
    return {"ok": True, "path": os.path.abspath(path), "provider": info}


def test_stt(payload):
    import stt_client
    pref = (payload.get("provider") or cfg.get("stt", {}).get("provider") or "auto")
    if pref == "winh":
        try:
            text = stt_client.dictate_windows(max_seconds=float(payload.get("max_seconds") or 12))
        except Exception as e:
            return {"ok": False, "error": "winh: %s" % e}
        return {"ok": True, "text": text or "", "provider": "winh"}
    av = stt_client.available_providers()
    if not av.get("record"):
        return {"ok": False, "error": "нет записи с микрофона (установи компоненты: sounddevice, numpy)"}
    try:
        wav = stt_client.record_audio(max_seconds=float(payload.get("max_seconds") or 3))
    except Exception as e:
        return {"ok": False, "error": "микрофон: %s" % e}
    text, info = stt_client.transcribe(wav)
    if text is None:
        return {"ok": False, "error": "распознавание: %s" % info}
    return {"ok": True, "text": text, "provider": info}


def deps_install():
    import subprocess
    import sys
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "-U", "edge-tts>=7.2.8", "sounddevice", "numpy"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                              cwd=BASE_DIR, creationflags=0x08000000)
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
    except Exception as e:
        return {"ok": False, "error": str(e)}
    ok = proc.returncode == 0
    # провайдеры пересчитываются лениво при каждом вызове available_providers()
    import tts_client
    import stt_client
    return {"ok": ok, "output": tail,
            "tts_available": tts_client.available_providers(),
            "stt_available": stt_client.available_providers()}


# --------------------------------------------------------- runtime state ---
# Текущая локация игрока (сообщается клиентом Ren'Py). Нужна окну настроек,
# чтобы показать маркер «вы здесь» на вкладке «Карта».
_CURRENT_STATE = {"loc": None, "loc_name": None}


def state_get():
    return {"ok": True, "loc": _CURRENT_STATE.get("loc"),
            "loc_name": _CURRENT_STATE.get("loc_name")}


def state_set_loc(payload):
    loc = payload.get("loc")
    _CURRENT_STATE["loc"] = (str(loc) if loc is not None else None)
    name = payload.get("loc_name")
    if name is not None:
        _CURRENT_STATE["loc_name"] = name
    return {"ok": True}


# -------------------------------------------------------------------- http ---

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # тихий лог; ошибки печатаем вручную

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(health())
        elif self.path.startswith("/config"):
            self._send(get_config_state())
        elif self.path.startswith("/state"):
            self._send(state_get())
        elif self.path.startswith("/history"):
            import urllib.parse
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            cid = (q.get("character") or [""])[0]
            self._send(history_get(cid))
        else:
            self._send({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                payload = {}

            if self.path.startswith("/state/loc"):
                out = state_set_loc(payload)
            elif self.path.startswith("/chat"):
                out = chat(payload)
            elif self.path.startswith("/initiative"):
                out = initiative(payload)
            elif self.path.startswith("/cameo"):
                out = cameo(payload)
            elif self.path.startswith("/tts"):
                out = tts(payload)
            elif self.path.startswith("/stt/record"):
                out = stt_record(payload)
            elif self.path.startswith("/history/clear"):
                out = history_clear(payload)
            elif self.path.startswith("/history/summary"):
                out = history_set_summary(payload)
            elif self.path.startswith("/history/compress"):
                out = history_compress(payload)
            elif self.path.startswith("/config/set"):
                out = config_set(payload)
            elif self.path.startswith("/keys/set"):
                out = keys_set(payload)
            elif self.path.startswith("/test/llm"):
                out = test_llm()
            elif self.path.startswith("/test/tts"):
                out = test_tts(payload)
            elif self.path.startswith("/test/stt"):
                out = test_stt(payload)
            elif self.path.startswith("/deps/install"):
                out = deps_install()
            elif self.path.startswith("/ui/settings"):
                out = open_settings_ui()
            elif self.path.startswith("/reload"):
                out = reload_config()
            elif self.path.startswith("/shutdown"):
                self._send({"ok": True})
                threading.Thread(target=_shutdown_server, daemon=True).start()
                return
            else:
                out = {"ok": False, "error": "not_found"}
            self._send(out)
        except BrokenPipeError:
            pass
        except Exception:
            traceback.print_exc()
            try:
                self._send({"ok": False, "error": "internal_error"}, 500)
            except Exception:
                pass


_server = None


def _shutdown_server():
    def stop():
        if _server:
            _server.shutdown()
    threading.Thread(target=stop, daemon=True).start()


def _print_banner():
    h = health()
    print("=" * 62)
    print("  ES AI Server  |  %s:%s" % (cfg.get("host", "127.0.0.1"), cfg.get("port", 40310)))
    print("-" * 62)
    print("  LLM : %s (%s)%s" % (h["llm"]["model"], h["llm"]["url"],
                                 "" if h["llm"]["key_present"] else "  [БЕЗ КЛЮЧА — localhost-only]"))
    print("  TTS : %s" % (h["tts"]["provider"] or "недоступен (установи edge-tts или укажи ключ)"))
    print("  STT : %s (микрофон: %s)" % (
        h["stt"]["transcriber"] or "недоступен",
        "да" if h["stt"]["mic"] else "нет (pip install sounddevice numpy)"))
    print("  Персонажи: " + ", ".join(c["name"] for c in h["characters"]))
    print("=" * 62)


def run_check():
    """python main.py --check — проверка конфигурации без запуска сервера."""
    h = health()
    print(json.dumps(h, ensure_ascii=False, indent=2))
    return 0


DEFAULT_PORT = 40310  # хвост id мастерской 3809240310
# 4999 совпадал с KCD2 AI NPC; 33147 — прежний дефолт (по appid)
OLD_DEFAULT_PORTS = (4999, 33147)


def migrate_port():
    """Разовый перенос со старых дефолтов (4999, 33147) на 40310."""
    if int(cfg.get("port", 0)) in OLD_DEFAULT_PORTS:
        cfg["port"] = DEFAULT_PORT
        config_loader.save_config()


def main():
    migrate_port()
    # Запуск через pythonw (.pyw): stdout отсутствует — пишем в файл
    if sys.stdout is None:
        logf = open(os.path.join(config_loader.user_data_dir(), "server_out.log"),
                    "a", buffering=1, encoding="utf-8")
        sys.stdout = logf
        sys.stderr = logf
    if "--check" in sys.argv:
        sys.exit(run_check())
    global _server
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", DEFAULT_PORT))
    _server = ThreadingHTTPServer((host, port), Handler)
    _print_banner()
    try:
        _server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

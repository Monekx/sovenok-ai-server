# -*- coding: utf-8 -*-
"""Загрузка персонажей, синонимов эмоций и правил ответа.

Эмоции и их словари синхронизированы с реальными тегами спрайтов игры
(извлечены из sprites.rpyc).
"""
import json
import os
import random
import shutil
import sys


def _get_base_dir():
    """Каталог с исполняемым файлом/скриптом (вне папки _internal PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_DIR = _get_base_dir()

_data = None
_by_id = {}


def _user_path():
    """Пользовательская копия es_characters.json (в ~/.config/AI.Sovenok)."""
    try:
        from config_loader import user_data_dir
        return os.path.join(user_data_dir(), "es_characters.json")
    except Exception:
        return _get_default_characters_path()


def _get_default_characters_path():
    """Поиск эталонного es_characters.json в бандле PyInstaller или проекте."""
    try:
        from config_loader import get_template_path
        p = get_template_path("es_characters.json")
        if os.path.isfile(p):
            return p
    except Exception:
        pass

    # Fallback-цепочка путей внутри PyInstaller (_MEIPASS / _internal)
    base = getattr(sys, "_MEIPASS", _DIR)
    candidates = [
        os.path.join(base, "src", "json", "es_characters.json"),
        os.path.join(base, "json", "es_characters.json"),
        os.path.join(base, "es_characters.json"),
        os.path.join(_DIR, "src", "json", "es_characters.json"),
        os.path.join(_DIR, "es_characters.json"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0]


def _load():
    global _data, _by_id
    if _data is not None:
        return

    path = _user_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            _data = json.load(f)
    except Exception:
        # Если пользовательского файла еще нет или он поврежден — читаем эталон
        default_path = _get_default_characters_path()
        try:
            with open(default_path, "r", encoding="utf-8") as f:
                _data = json.load(f)
        except Exception as e:
            print(f"[CHARACTERS ERROR] Не удалось прочитать дефолтный файл {default_path}: {e}")
            _data = {"characters": [], "player": {}}

        # И сразу засеиваем им пользовательский каталог
        try:
            from config_loader import user_data_dir
            dst = os.path.join(user_data_dir(), "es_characters.json")
            if not os.path.exists(dst) and os.path.isfile(default_path):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(default_path, dst)
        except Exception as e:
            print(f"[CHARACTERS WARN] Ошибка копирования эталона: {e}")

    _by_id = {c["id"]: c for c in _data.get("characters", [])}

def characters():
    _load()
    return _data.get("characters", [])


def get_player():
    _load()
    return _data.get("player") or {}


def player_block():
    """Блок о ГГ для system-промпта: имя и характер, заданные игроком."""
    p = get_player()
    if not p:
        return ""
    name = (p.get("name") or "").strip() or u"Семён"
    persona = (p.get("persona") or "").strip()
    if not persona:
        return u"Твой собеседник: его зовут %s." % name
    return u"Твой собеседник: его зовут %s. О нём: %s" % (name, persona)


def reload():
    """Перечитать es_characters.json (после правки персон из окна настроек)."""
    global _data, _by_id
    _data = None
    _by_id = {}
    _load()


def get_character(char_id):
    _load()
    ch = _by_id.get(char_id)
    if ch is None:
        ch = _by_id.get("un")
    return ch


def synonyms():
    _load()
    return _data.get("emotion_synonyms_ru", {})


def emotions_for(char_id):
    """Реальный список эмоций персонажа (из спрайтов игры)."""
    _load()
    ch = get_character(char_id)
    emo = set()
    for c in _data.get("characters", []):
        if c.get("id") == ch.get("id"):
            emo = _EMOTIONS.get(ch.get("id"), set())
    return emo


# Словари эмоций по данным sprites.rpyc (валидные теги: "{id} {эмоция} {dress} [close|far]")
_EMOTIONS = {
    "sl": {"angry", "happy", "laugh", "normal", "sad", "scared", "serious", "shy", "smile", "smile2", "surprise", "tender"},
    "dv": {"angry", "cry", "grin", "guilty", "laugh", "normal", "rage", "sad", "scared", "shocked", "shy", "smile", "surprise"},
    "un": {"angry", "angry2", "cry", "cry_smile", "evil_smile", "grin", "laugh", "normal", "rage", "sad", "scared", "serious", "shocked", "shy", "smile", "smile2", "smile3", "surprise"},
    "mi": {"angry", "cry", "cry_smile", "dontlike", "grin", "happy", "laugh", "normal", "rage", "sad", "scared", "serious", "shocked", "shy", "smile", "surprise", "upset"},
    "us": {"angry", "calml", "cry", "cry2", "dontlike", "fear", "grin", "laugh", "laugh2", "normal", "sad", "shy", "shy2", "smile", "surp1", "surp2", "surp3", "upset"},
    "sh": {"cry", "laugh", "normal", "normal_smile", "rage", "scared", "serious", "smile", "surprise", "upset"},
    "mt": {"angry", "grin", "laugh", "normal", "rage", "sad", "scared", "shocked", "smile", "surprise"},
    "uv": {"normal", "smile", "laugh", "grin", "sad", "dontlike", "guilty", "shocked", "surprise", "surprise2", "upset", "rage"},
    "el": {"normal", "smile", "laugh", "grin", "sad", "serious", "scared", "shocked", "surprise", "upset", "angry"},
    "mz": {"normal", "smile", "laugh", "angry", "rage", "shy"},
    "cs": {"normal", "shy", "smile"},
}

# Перевод универсальной эмоции в допустимую для конкретного персонажа
_FALLBACKS = {
    "shy": ["shy", "smile", "normal"],
    "smile": ["smile", "smile2", "happy", "normal"],
    "sad": ["sad", "cry", "upset", "normal"],
    "angry": ["angry", "rage", "dontlike", "normal"],
    "surprise": ["surprise", "shocked", "surp1", "normal"],
    "scared": ["scared", "fear", "shocked", "normal"],
    "laugh": ["laugh", "laugh2", "grin", "happy", "normal"],
    "happy": ["happy", "smile", "laugh", "normal"],
    "cry": ["cry", "cry2", "cry_smile", "sad", "normal"],
    "rage": ["rage", "angry", "normal"],
    "shocked": ["shocked", "surprise", "normal"],
    "grin": ["grin", "laugh", "smile", "normal"],
    "serious": ["serious", "normal"],
    "tender": ["tender", "smile", "normal"],
    "upset": ["upset", "sad", "dontlike", "normal"],
    "dontlike": ["dontlike", "angry", "normal"],
    "guilty": ["guilty", "sad", "normal"],
    "normal": ["normal"],
}


def map_emotion(char_id, raw_emotion):
    """RU-слово или универсальный ключ -> валидная эмоция персонажа."""
    _load()
    ch = get_character(char_id)
    vocab = _EMOTIONS.get(ch["id"], {"normal", "smile", "sad", "angry", "shy", "laugh", "surprise", "scared", "cry"})
    raw = (raw_emotion or "").strip().lower()
    if not raw:
        raw = "нормально"
    if raw in vocab:
        return raw
    syn = synonyms()
    key = syn.get(raw)
    if key is None:
        key = raw
    for cand in _FALLBACKS.get(key, [key, "normal"]):
        if cand in vocab:
            return cand
    return "normal"


def random_emotion_ru(char_id):
    """Случайная частая эмоция — для правила формата в промпте."""
    return random.choice(["нормально", "улыбка", "смущение", "грусть", "смех"])


def reply_rules(ch):
    vocab = sorted(_EMOTIONS.get(ch["id"], []))
    guard = ""
    try:
        _age = int(ch.get("age") or 99)
    except (TypeError, ValueError):
        _age = 99
    if _age < 18:
        guard = (
            "0. ВАЖНО (приоритет над всем): ты несовершеннолетний ребёнок. Любые "
            "романтические, интимные, флиртовые или сексуальные темы для тебя недопустимы "
            "и неинтересны. Если Семён заигрывает — реагируй как ребёнок: не понимаешь, "
            "«фу», дразнишься, меняешь тему на игры и шалости. Никогда не переодевайся в "
            "купальник «для настроения» — только чтобы искупаться, без всякого подтекста.\n"
        )
    return guard + (
        "ПРАВИЛА ОТВЕТА:\n"
        "1. Ты живой человек, а не ИИ, программа или языковая модель. Никогда не упоминай "
        "искусственный интеллект, нейросети, модели, промпты.\n"
        "2. Ты живёшь в СССР, в пионерлагере «Совёнок», 1980-е. Ты не знаешь про интернет, "
        "смартфоны и современные вещи. Если Семён говорит странное про будущее — считай это "
        "странной шуткой или выдумкой.\n"
        "3. Отвечай ТОЛЬКО по-русски, живой разговорной речью, от первого лица.\n"
        "4. Ответ — 1-4 коротких предложения. Без списков, без markdown, без кавычек вокруг речи.\n"
        "5. Меняй место действия ТОЛЬКО если Семён сам предложил пойти куда-то или явно согласился "
        "на твоё предложение: добавь В САМОМ КОНЦЕ ответа тег [action:goto:ID]. "
        "Доступные ID: beach (пляж), island (остров), square (площадь), polyana (поляна), "
        "path (тропа), playground (спортплощадка), musclub (музклуб), stage (сцена), "
        "dining (столовая), library (библиотека), camp_gate (ворота лагеря), "
        "bus_gate (автобус у ворот), bus_inside (внутри автобуса), mt_room (комната вожатой), "
        "houses (аллея домиков), clubs (клубы снаружи), club_room (внутри клуба кибернетиков), "
        "aidpost (медпункт снаружи), aidpost_inside (внутри медпункта), boathouse (причал), "
        "washstand (умывальники), road (дорога), dv_room/sl_room/un_room (домики героинь внутри), "
        "old_building (старый корпус), catacombs (катакомбы), mine (шахта), "
        "semen_room (комната Семёна), bathhouse (баня), musclub_inside (внутри музклуба), "
        "bus_stop (автобусная остановка), dining_ext (площадка у столовой), "
        "stage_big (большая концертная сцена), gate_no_bus (ворота, автобус уехал), "
        "dv_house_ext/mt_house_ext/sl_house_ext/un_house_ext (домики снаружи). "
        "Переходи предпочтительно в места, логично соседние с текущим (они перечислены "
        "в описании места действия). "
        "И время суток: [action:time:день], [action:time:закат] или [action:time:ночь]. "
        "6. Наряд по контексту (не обязателен): у воды героиня и так в купальнике. Если "
        "стало холодно, разговор серьёзный или Семён просит одеться — добавь в конце "
        "[action:dress:форма]. Если решили искупаться/позагорать — [action:dress:купальник]. "
        "В романтической вечерней сцене или наедине в комнате [action:dress:купальник] уместен, "
        "только если это естественно по настроению. Без причины наряд не меняй. "
        "Теги читаются игрой молча — вслух их не произноси. "
        "КАЖДЫЙ ответ начинай с эмоции в скобках — одно слово из этого списка: "
        "(нормально), (улыбка), (смущение), (грусть), (злость), (удивление), (страх), (смех), "
        "(радость), (плачь), (ярость), (шок), (усмешка), (серьёзность), (обида).\n"
        "Пример: (смущение) П-правда? Мне приятно...\n"
        "Допустимые эмоции персонажа: %s." % ", ".join(vocab)
    )

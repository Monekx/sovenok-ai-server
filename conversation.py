# -*- coding: utf-8 -*-
"""История разговоров по персонажам, персистентность и LLM-сжатие памяти.

Порт схемы kcd2-ai-npc: скользящее окно + суммаризация старых
сообщений лёгким LLM-запросом в compressed_summary.
"""
import json
import os
import sys
import threading

lock = threading.Lock()

# char_id -> {"messages": [{"role": ..., "content": ...}], "summary": str, "summarized_count": int}
conversations = {}
_loaded = False


def _get_fallback_dir():
    """Каталог приложения рядом с бинарником на случай отказа хранилища."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "memory", "conversations")


def _dir():
    try:
        from config_loader import user_data_dir
        target = os.path.join(user_data_dir(), "memory", "conversations")
    except Exception:
        target = _get_fallback_dir()
    os.makedirs(target, exist_ok=True)
    return target


def _path(char_id):
    safe = "".join(c for c in char_id if c.isalnum() or c in "-_")
    if not safe:
        safe = "unknown"
    return os.path.join(_dir(), "%s.json" % safe)


def load():
    """Загрузка всех сохраненных историй из папки пользователя."""
    global _loaded
    target_dir = _dir()
    if not os.path.isdir(target_dir):
        _loaded = True
        return

    with lock:
        for fn in os.listdir(target_dir):
            if not fn.endswith(".json"):
                continue
            char_id = fn[:-5]
            file_path = os.path.join(target_dir, fn)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        conversations[char_id] = data
            except Exception as e:
                print(f"[MEMORY WARN] Не удалось прочитать историю {file_path}: {e}")
        _loaded = True


def _ensure_loaded():
    if not _loaded:
        load()


def _persist_unlocked(char_id):
    """Атомарная запись истории персонажа во временный файл с последующей заменой."""
    data = conversations.get(char_id, {})
    target_path = _path(char_id)
    tmp_path = target_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        if sys.platform == "win32" and os.path.exists(target_path):
            os.replace(tmp_path, target_path)
        else:
            os.rename(tmp_path, target_path)
    except Exception as e:
        print(f"[MEMORY ERROR] Ошибка сохранения истории {char_id}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def get_history(char_id):
    _ensure_loaded()
    with lock:
        conv = conversations.get(char_id, {})
        return list(conv.get("messages", [])), conv.get("summary", "")


def set_summary(char_id, summary):
    """Ручная правка выжимки из окна настроек."""
    _ensure_loaded()
    with lock:
        conv = conversations.setdefault(char_id, {"messages": [], "summary": ""})
        conv["summary"] = (summary or "").strip()
        _persist_unlocked(char_id)
        return conv["summary"]


def add_exchange(char_id, user_text, assistant_text):
    _ensure_loaded()
    with lock:
        conv = conversations.setdefault(char_id, {"messages": [], "summary": ""})
        conv.setdefault("messages", []).append({"role": "user", "content": user_text})
        conv["messages"].append({"role": "assistant", "content": assistant_text})
        _persist_unlocked(char_id)


def clear(char_id):
    _ensure_loaded()
    with lock:
        conversations[char_id] = {"messages": [], "summary": "", "summarized_count": 0}
        _persist_unlocked(char_id)


def _format_for_summary(messages, old_summary, player_name="Семён"):
    lines = []
    if old_summary:
        lines.append("Что уже было в памяти: " + old_summary)
    for m in messages:
        who = player_name if m.get("role") == "user" else "Персонаж"
        lines.append("%s: %s" % (who, m.get("content") or ""))
    return "\n".join(lines)


def maybe_compress(char_id, cfg, llm_chat_fn, force=False):
    """Старые реплики сжимаются в summary. Полный лог остаётся в хранилище.

    В модель уходит summary + хвост последних сообщений.
    llm_chat_fn(text) -> str.
    """
    _ensure_loaded()
    hcfg = cfg.get("history", {})
    threshold = int(hcfg.get("compress_threshold", 16))
    keep_recent = int(hcfg.get("keep_recent", 6))

    with lock:
        conv = conversations.get(char_id)
        if not conv:
            return False
        msgs = list(conv.get("messages", []))
        done = int(conv.get("summarized_count") or 0)
        pending_end = max(0, len(msgs) - keep_recent)

        if force and (pending_end <= done or not msgs[done:pending_end]):
            chunk = msgs
            pending_end = max(done, len(msgs) - keep_recent)
        else:
            if not force and pending_end - done < max(2, threshold - keep_recent):
                return False
            if pending_end <= done:
                return False
            chunk = msgs[done:pending_end]

        if not chunk:
            return False
        old_summary = conv.get("summary", "")

    text = _format_for_summary(chunk, old_summary)
    try:
        summary = llm_chat_fn(text).strip()
    except Exception as e:
        print(f"[MEMORY COMPRESS ERROR] Сбой запроса сжатия: {e}")
        return False

    if not summary:
        return False

    with lock:
        conv = conversations.setdefault(char_id, {"messages": []})
        conv["summary"] = summary
        conv["summarized_count"] = pending_end
        _persist_unlocked(char_id)
    return True


def build_history_block(char_id, cfg, novel_context=None, novel_who="", location=""):
    """Собирает messages для LLM: system-промпт персонажа + summary + окно истории."""
    _ensure_loaded()
    hcfg = cfg.get("history", {})
    max_messages = int(hcfg.get("max_messages", 16))
    keep_recent = int(hcfg.get("keep_recent", 6))

    hist, summary = get_history(char_id)
    # Если уже есть выжимка, берем короткий контекст, иначе расширенное окно
    window = hist[-(keep_recent if summary else max_messages):]

    sys_prompt = build_system_prompt(char_id, novel_context, novel_who, summary, location)
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(window)
    return messages


def build_system_prompt(char_id, novel_context=None, novel_who="", summary="", location=""):
    from characters_store import get_character, reply_rules, player_block
    ch = get_character(char_id)
    parts = [ch.get("persona", ""), ch.get("speech", ""), reply_rules(ch)]

    pb = player_block()
    if pb:
        parts.append(pb)
    if location:
        parts.append("Текущее место действия (где вы сейчас): " + location + ". Не противоречь этой локации в описаниях и репликах.")
    if summary:
        parts.append("Память о прошлых разговорах:\n" + summary)
    if novel_context:
        lines = []
        for item in novel_context:
            who = item.get("who") or ""
            what = (item.get("what") or "").strip()
            if what:
                lines.append("%s: %s" % (who or "...", what))
        if lines:
            parts.append(
                "Сейчас идёт игра: это последние события новеллы «Бесконечное лето».\n"
                + "\n".join(lines)
            )
    if novel_who:
        parts.append("С тобой сейчас говорит: %s." % novel_who)
    return "\n\n".join(p for p in parts if p)

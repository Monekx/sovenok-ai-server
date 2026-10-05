# -*- coding: utf-8 -*-
"""Конфиг и ключи: config.json + keys.json.

Шаблоны лежат внутри бандла в src/json/*.json.
Реальные рабочие файлы создаются и читаются строго из папки пользователя:
  - Windows: %LOCALAPPDATA%/AI.Sovenok
  - Linux:   $XDG_CONFIG_HOME/AI.Sovenok (или ~/.config/AI.Sovenok)
"""
import json
import os
import shutil
import sys
import threading


def _get_base_dir():
    """Путь к ресурсам внутри PyInstaller (_MEIPASS) или корень проекта."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    # Если запущен из src/ или корня — берем корень
    cur = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(cur) == "src":
        return os.path.dirname(cur)
    return cur


_BASE_DIR = _get_base_dir()
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "src", "json")
_DATA_DIR_NAME = "AI.Sovenok"
_USER_DIR = None
_lock = threading.Lock()

cfg = {}
keys = {}


def user_data_dir():
    """Папка пользовательских данных вне установки (переживает апдейты Steam)."""
    global _USER_DIR
    if _USER_DIR is None:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")

        target_dir = os.path.join(base, _DATA_DIR_NAME)
        try:
            os.makedirs(target_dir, exist_ok=True)
            _USER_DIR = target_dir
        except Exception as e:
            print(f"[CONFIG WARN] Ошибка доступа к {target_dir}: {e}. Используем fallback.")
            _USER_DIR = _BASE_DIR
    return _USER_DIR


def get_template_path(filename):
    """Возвращает путь к дефолтному шаблону в src/json/."""
    candidates = [
        os.path.join(_TEMPLATES_DIR, filename),
        os.path.join(_BASE_DIR, "json", filename),
        os.path.join(_BASE_DIR, filename),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def seed_user_data():
    """Засеивает пользовательскую папку дефолтными JSON из src/json, если их там ещё нет."""
    u = user_data_dir()
    os.makedirs(u, exist_ok=True)

    # 1. Шаблоны, которые нужно распаковать новичку
    for filename in ("config.json", "keys.json", "es_characters.json"):
        dst = os.path.join(u, filename)
        if not os.path.exists(dst):
            src = get_template_path(filename)
            if os.path.exists(src):
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    print(f"[CONFIG SEED ERROR] {src} -> {dst}: {e}")

    # 2. Обратная совместимость: если у юзера остались старые данные в папке мода
    legacy_roots = [_BASE_DIR, os.path.dirname(_BASE_DIR)]
    dst_mem = os.path.join(u, "memory", "conversations")
    if not os.path.isdir(dst_mem):
        for root in legacy_roots:
            src_mem = os.path.join(root, "memory", "conversations")
            if os.path.isdir(src_mem):
                try:
                    shutil.copytree(src_mem, dst_mem)
                    break
                except Exception:
                    pass


def _read(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CONFIG WARN] Ошибка чтения {path}: {e}")
    return default


def reload_all():
    """Перечитывает пользовательские файлы из user_data_dir."""
    global cfg, keys
    seed_user_data()
    u = user_data_dir()
    new_cfg = _read(os.path.join(u, "config.json"), {})
    new_keys = _read(os.path.join(u, "keys.json"), {})
    with _lock:
        cfg.clear()
        cfg.update(new_cfg)
        keys.clear()
        keys.update(new_keys)
    return cfg


def save_config():
    with _lock:
        path = os.path.join(user_data_dir(), "config.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            print(f"[CONFIG ERROR] Ошибка сохранения {path}: {e}")


def save_keys():
    with _lock:
        path = os.path.join(user_data_dir(), "keys.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(keys, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            print(f"[CONFIG ERROR] Ошибка сохранения {path}: {e}")


reload_all()

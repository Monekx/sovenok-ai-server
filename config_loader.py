# -*- coding: utf-8 -*-
"""Конфиг и ключи: config.json (настройки) + keys.json (секреты).

Пользовательские данные (ключи, настройки, история, персоны, логи) живут ВНЕ
папки мода:
  - Windows: %LOCALAPPDATA%/AI.Sovenok
  - Linux:   $XDG_CONFIG_HOME/AI.Sovenok (или ~/.config/AI.Sovenok)

Steam может перезалить папку мастерской в любой момент и стереть всё внутри,
поэтому хранить пользовательские данные в папке мода нельзя.
"""
import json
import os
import shutil
import sys
import threading


def _get_base_dir():
    """Каталог с исполняемым файлом или скриптом (вне папки _internal PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_DIR = _get_base_dir()
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
            _USER_DIR = _DIR
    return _USER_DIR


def _copy_if_missing(src, dst):
    if not src or not dst or os.path.exists(dst) or not os.path.exists(src):
        return
    try:
        parent = os.path.dirname(dst)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception as e:
        print(f"[CONFIG MIGRATE WARN] {src} -> {dst}: {e}")


def migrate_user_data():
    """Старые пользовательские файлы из папки мода -> в папку данных (идемпотентно)."""
    u = user_data_dir()
    if os.path.abspath(u) == os.path.abspath(_DIR):
        return

    # Проверяем файлы рядом с бинарником (server/windows или server/linux),
    # а также на уровень выше (server/) на случай старой структуры
    possible_roots = [_DIR, os.path.dirname(_DIR)]

    for filename in ("config.json", "keys.json", "es_characters.json"):
        dst = os.path.join(u, filename)
        if not os.path.exists(dst):
            for root in possible_roots:
                src = os.path.join(root, filename)
                if os.path.exists(src):
                    _copy_if_missing(src, dst)
                    break

    dst_mem = os.path.join(u, "memory", "conversations")
    if not os.path.isdir(dst_mem):
        for root in possible_roots:
            src_mem = os.path.join(root, "memory", "conversations")
            if os.path.isdir(src_mem):
                try:
                    shutil.copytree(src_mem, dst_mem)
                    break
                except Exception as e:
                    print(f"[CONFIG MIGRATE WARN] memory: {e}")


def _read(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CONFIG WARN] {path}: {e}")
    return default


def reload_all():
    """In-place обновление: сохраняет ссылки на единые dict-объекты."""
    global cfg, keys
    migrate_user_data()
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Совёнок — открытие окна настроек двойным кликом.

Если сервер ещё не запущен — поднимет его сам (без консоли), затем откроет
нативное окно настроек.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DETACHED = 0x00000008 if os.name == "nt" else 0


def read_port():
    try:
        with open(os.path.join(DIR, "config.json"), "r", encoding="utf-8") as f:
            port = int(json.load(f).get("port", 40310))
    except Exception:
        return 40310
    # старые дефолты сервер при старте мигрирует на 40310 (main.migrate_port)
    return 40310 if port in (4999, 33147) else port


PORT = read_port()


def server_alive():
    try:
        urllib.request.urlopen("http://127.0.0.1:%s/health" % PORT, timeout=2)
        return True
    except Exception:
        return False


if not server_alive():
    subprocess.Popen([sys.executable, os.path.join(DIR, "main.py")],
                     cwd=DIR, creationflags=NO_WINDOW | DETACHED if os.name == "nt" else 0)
    for _ in range(30):
        time.sleep(0.5)
        if server_alive():
            break

sys.path.insert(0, DIR)
from settings_window import run_settings_window, _log_window_error, _show_error_box  # noqa

try:
    run_settings_window()
except Exception:
    import traceback
    _log_window_error(traceback.format_exc())
    _show_error_box(traceback.format_exc())
    raise

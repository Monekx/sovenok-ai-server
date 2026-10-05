#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручной запуск ES AI Server без окна консоли.

Двойной клик по этому файлу (или pythonw.exe start_server.pyw).
Сервер пишет лог в server_out.log рядом.
"""
import os
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
DETACHED = 0x00000008 if os.name == "nt" else 0
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

subprocess.Popen(
    [sys.executable, os.path.join(DIR, "main.py")],
    cwd=DIR,
    creationflags=DETACHED | NO_WINDOW if os.name == "nt" else 0,
)

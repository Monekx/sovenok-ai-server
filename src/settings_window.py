#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Совёнок — кроссплатформенное нативное окно настроек.
Оптимизировано для сборки через PyInstaller (встроенный Pillow, XDG/AppData пути).
"""
import base64
import json
import math
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

def _get_base_dir():
    """Путь к ресурсам внутри PyInstaller (_MEIPASS) или рядом со скриптом."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()
sys.path.insert(0, BASE_DIR)

import config_loader
import llm_client
import tts_client
import stt_client
import ui_i18n
from characters_store import characters, get_character

config_loader.reload_all()
cfg = config_loader.cfg
ui_lang = [cfg.get("ui_lang") if cfg.get("ui_lang") in ("ru", "en") else "ru"]

def tr(text):
    return ui_i18n.tr(text, ui_lang[0])

keys = config_loader.keys
_T0 = time.time()

# ---------------------------------------------------------------- провайдеры --
LLM_PROVIDERS = ["Groq", "Mistral", "OpenRouter", "OpenAI", "VseGPT", "ProxyAPI",
                 "NVIDIA", "Cohere", "GitHub", "Ollama", "LM Studio", "Свой"]
LLM_PRESETS = {
    "Groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "groq_api_key"),
    "Mistral": ("https://api.mistral.ai/v1", "mistral-small-latest", "mistral_api_key"),
    "OpenRouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct", "llm_api_key"),
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini", "openai_api_key"),
    "VseGPT": ("https://api.vsegpt.ru/v1", "", "vsegpt_api_key"),
    "ProxyAPI": ("https://api.proxyapi.ru/openai/v1", "gpt-4o-mini", "proxyapi_api_key"),
    "NVIDIA": ("https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct", "nvidia_api_key"),
    "Cohere": ("https://api.cohere.ai/compatibility/v1", "command-a-03-2025", "cohere_api_key"),
    "GitHub": ("https://models.github.ai/inference", "openai/gpt-4o-mini", "github_api_key"),
    "Ollama": ("http://localhost:11434/v1", "llama3.1:8b", ""),
    "LM Studio": ("http://localhost:1234/v1", "local-model", ""),
    "Свой": ("http://127.0.0.1:8080/v1", "", "custom_llm_api_key"),
}

MODELS_URLS = {
    "GitHub": "https://models.github.ai/catalog/models",
    "Cohere": "https://api.cohere.com/v1/models?endpoint=chat&page_size=200",
}

FALLBACK_MODELS = {
    "Groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b", "qwen/qwen3-32b"],
    "OpenRouter": ["meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-chat-v3-0324:free", "google/gemini-2.0-flash-exp:free", "qwen/qwen3-235b-a22b:free"],
    "OpenAI": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    "Mistral": ["mistral-small-latest", "mistral-large-latest", "open-mistral-nemo"],
    "NVIDIA": ["meta/llama-3.3-70b-instruct", "deepseek-ai/deepseek-r1"],
}

PROVIDER_KEYNAME = {"groq": "groq_api_key", "mistral": "mistral_api_key",
                    "openrouter": "llm_api_key", "openai": "openai_api_key",
                    "vsegpt": "vsegpt_api_key", "proxyapi": "proxyapi_api_key",
                    "nvidia": "nvidia_api_key", "cohere": "cohere_api_key",
                    "github": "github_api_key"}

KEY_URLS = {
    "groq_api_key": "https://console.groq.com/keys",
    "mistral_api_key": "https://console.mistral.ai/api-keys/",
    "llm_api_key": "https://openrouter.ai/settings/keys",
    "openai_api_key": "https://platform.openai.com/api-keys",
    "vsegpt_api_key": "https://vsegpt.ru/",
    "proxyapi_api_key": "https://proxyapi.ru/",
    "nvidia_api_key": "https://build.nvidia.com/settings/api-keys",
    "cohere_api_key": "https://dashboard.cohere.com/api-keys",
    "github_api_key": "https://github.com/settings/personal-access-tokens",
    "elevenlabs_api_key": "https://elevenlabs.io/app/settings/api-keys",
    "fish_api_key": "https://fish.audio/app/api-keys/",
}

ALL_KEYS = ("groq_api_key", "mistral_api_key", "llm_api_key", "openai_api_key",
            "vsegpt_api_key", "proxyapi_api_key", "nvidia_api_key", "cohere_api_key",
            "github_api_key", "elevenlabs_api_key", "fish_api_key",
            "custom_tts_api_key", "custom_llm_api_key")

TTS_PROVIDERS = ["Авто", "ElevenLabs", "Fish Audio", "edge-tts", "OpenAI", "SAPI", "Свой", "Выключено"]
TTS_MAP = {"Авто": "auto", "ElevenLabs": "elevenlabs", "Fish Audio": "fish", "edge-tts": "edge",
           "OpenAI": "openai", "SAPI": "sapi", "Свой": "custom", "Выключено": "off"}
STT_PROVIDERS = ["Авто", "Groq Whisper", "OpenAI Whisper", "Локальный", "Windows Win+H"]
STT_MAP = {"Авто": "auto", "Groq Whisper": "groq", "OpenAI Whisper": "openai",
           "Локальный": "local", "Windows Win+H": "winh"}

DEFAULTS = {"provider": "Groq", "max_tokens": 400, "temperature": 0.9,
            "tts": "Авто", "stt": "Авто"}

# ------------------------------------------------------------- стиль игры --
WIN_W, WIN_H = 960, 720
MIN_W, MIN_H = 820, 640

PARCH = (241, 230, 202)
PARCH_FOCUS = (248, 240, 219)
PARCH_HEX = "#f1e6ca"
PARCH_FOCUS_HEX = "#f8f0db"
PARCH_EDGE = (146, 110, 62, 255)
HONEY = (234, 168, 66)
HONEY_EDGE = (150, 96, 30, 255)
INK = "#3a2913"
INK_SOFT = "#806a4a"
INK_ON_HONEY = "#2a1905"
CREAM = "#fff7e4"
LABEL = "#fbeccb"
SECTION = "#ffd27d"
HINT = "#efe1c3"
OUTLINE = "#150e05"
OK_GREEN = "#b8f5a6"
ERR_RED = "#ffb4a2"
DOT_IDLE = "#a99a7c"
DOT_OK = "#4fbf5d"
DOT_ERR = "#d9573f"

CHIP_STYLES = {
    "normal":        ((244, 234, 208, 226), (132, 98, 54, 210), INK, True),
    "hover":         ((251, 244, 224, 245), (214, 146, 46, 255), "#5b3a0c", True),
    "selected":      (HONEY + (255,), HONEY_EDGE, INK_ON_HONEY, True),
    "primary":       (HONEY + (255,), HONEY_EDGE, INK_ON_HONEY, True),
    "accent":        (HONEY + (255,), HONEY_EDGE, INK_ON_HONEY, True),
    "accent_hover":  ((246, 186, 88, 255), HONEY_EDGE, INK_ON_HONEY, True),
    "primary_hover": ((246, 186, 88, 255), HONEY_EDGE, INK_ON_HONEY, True),
    "tab":           ((0, 0, 0, 0), (0, 0, 0, 0), INK, False),
    "tab_hover":     ((255, 255, 255, 90), (0, 0, 0, 0), INK, False),
    "tab_selected":  (HONEY + (255,), HONEY_EDGE, INK_ON_HONEY, False),
}

ES_NAME_COLORS = {
    "un": "#b956ff", "sl": "#e0b800", "dv": "#ff9900", "us": "#ff5a2d",
    "mi": "#00c8e6", "mt": "#1fbf3a", "mz": "#5f7cff", "el": "#d6c400",
    "sh": "#d9c61e", "cs": "#8f8fff", "uv": "#3fbf3f", "player": "#8a6a3a",
}

_LAST_ROOT = [None]
_mutex_sock = None

def _already_running():
    global _mutex_sock
    _mutex_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Универсальный lock через локальный сокет (кроссплатформенно)
        _mutex_sock.bind(("127.0.0.1", 40311))
        return False
    except socket.error:
        return True

def _server_port():
    port = int(cfg.get("port", 40310))
    return 40310 if port in (4999, 33147) else port

def _server_url():
    return "http://127.0.0.1:%s" % _server_port()

def _post(path, payload=None, timeout=5):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(_server_url() + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace"))

def play_mp3(path):
    try:
        if sys.platform == "win32":
            import ctypes
            mci = ctypes.windll.winmm
            mci.mciSendStringW(u"close esAITTS", None, 0, 0)
            mci.mciSendStringW(u'open "%s" type mpegvideo alias esAITTS' % path, None, 0, 0)
            mci.mciSendStringW(u"play esAITTS", None, 0, 0)
            return True
        else:
            for player in ["mpv", "ffplay", "mpg123", "mplayer"]:
                if subprocess.call(["which", player], stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0:
                    args = [player, "--no-video", "--really-quiet", path] if player == "mpv" else \
                           [player, "-nodisp", "-autoexit", path] if player == "ffplay" else [player, path]
                    subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    return True
            return False
    except Exception as e:
        open_folder(path)
        return False

def open_folder(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print(f"Failed to open path: {e}")

# --------------------------------------------------- карта лагеря (вкладка) --
ES_MAP_IMG_W, ES_MAP_IMG_H = 1178.0, 663.0
ES_MAP_PIN = {
    "square": (588, 280), "camp_gate": (283, 300), "gate_no_bus": (210, 292),
    "bus_gate": (150, 285), "bus_inside": (120, 280), "bus_stop": (90, 275),
    "road": (110, 288), "houses": (450, 345),
    "dv_house_ext": (600, 128), "dv_room": (600, 128),
    "sl_house_ext": (450, 405), "sl_room": (450, 405),
    "un_house_ext": (430, 445), "un_room": (430, 445),
    "mt_house_ext": (512, 245), "mt_room": (512, 245),
    "semen_room": (560, 152),
    "dining_ext": (660, 322), "dining": (660, 322),
    "clubs": (355, 288), "club_room": (355, 288),
    "musclub": (400, 190), "musclub_inside": (400, 190),
    "library": (748, 195), "stage": (680, 58), "stage_big": (680, 58),
    "playground": (850, 315), "aidpost": (660, 237), "aidpost_inside": (660, 237),
    "path": (400, 112), "polyana": (300, 92), "washstand": (460, 297),
    "beach": (820, 455), "island": (400, 600), "boathouse": (547, 517),
    "bathhouse": (500, 470), "old_building": (177, 615),
    "catacombs": (205, 598), "mine": (235, 582),
}

def _load_map_pil():
    """Загрузка карты лагеря из папки ui через Pillow."""
    candidates = [
        os.path.join(BASE_DIR, "src", "ui", "es_ai_map_bg_png.png"),
        os.path.join(BASE_DIR, "ui", "es_ai_map_bg_png.png"),
        os.path.join(BASE_DIR, "src", "ui", "es_ai_map_bg_png.png"),
        os.path.join(BASE_DIR, "ui", "es_ai_map_bg_png.png"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return Image.open(path).convert("RGB")
            except Exception as e:
                print(f"[MAP ERROR] Ошибка загрузки {path}: {e}")
    return None

SP = 6

def _pill_image(w, h, fill, border, radius=None, shadow=True, gloss=True, bw=1):
    s = 3
    r = (h // 2) if radius is None else radius
    sp = SP if shadow else 0
    W, H = (w + 2 * sp) * s, (h + 2 * sp) * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            (sp * s, (sp + 2) * s, (sp + w) * s, (sp + h + 2) * s), radius=r * s, fill=(18, 10, 2, 120))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(2.6 * s)))
    body = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    ImageDraw.Draw(body).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s, fill=fill)
    if gloss and fill[3] > 0:
        mask = body.split()[3]
        g = Image.linear_gradient("L").resize((w * s, h * s))
        g = g.point(lambda v: max(0, 150 - v) * 55 // 150)
        gl = Image.new("RGBA", (w * s, h * s), (255, 255, 255, 0))
        gl.putalpha(ImageChops.multiply(g, mask))
        body.alpha_composite(gl)
    if border and border[3] > 0:
        ImageDraw.Draw(body).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s,
                                               outline=border, width=bw * s)
    im.alpha_composite(body, (sp * s, sp * s))
    return im.resize((w + 2 * sp, h + 2 * sp), Image.LANCZOS), sp

def _magnifier_image(size=18, color=(58, 41, 19, 255), bg=PARCH):
    s = 4
    im = Image.new("RGBA", (size * s, size * s), bg + (255,))
    d = ImageDraw.Draw(im)
    c = size * s * 0.42
    r = size * s * 0.27
    d.ellipse((c - r, c - r, c + r, c + r), outline=color, width=int(2.0 * s))
    d.line((c + r * 0.72, c + r * 0.72, size * s * 0.86, size * s * 0.86), fill=color, width=int(2.6 * s))
    return im.resize((size, size), Image.LANCZOS)

def _compose_background(w, h):
    try:
        src = os.path.join(BASE_DIR, "ui", "bg_settings.jpg")
        if os.path.exists(src):
            img = Image.open(src).convert("RGB")
            scale = max(float(w) / img.width, float(h) / img.height)
            img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
            left = (img.width - w) // 2
            top = (img.height - h) // 2
            img = img.crop((left, top, left + w, top + h)).convert("RGBA")
        else:
            img = Image.new("RGBA", (w, h), (64, 110, 70, 255))
        gh = 96
        grad = Image.new("L", (1, gh))
        for yy in range(gh):
            grad.putpixel((0, yy), int(70 * (1 - yy / float(gh)) ** 1.8))
        shade = Image.new("RGBA", (w, gh), (10, 8, 4, 0))
        shade.putalpha(grad.resize((w, gh)))
        img.alpha_composite(shade, (0, 0))
        out = os.path.join(tempfile.gettempdir(), "es_ai_bg_%s.png" % os.getpid())
        img.convert("RGB").save(out)
        return out
    except Exception:
        return None

def _load_game_font():
    try:
        path = os.path.join(BASE_DIR, "ui", "gothic.ttf")
        if os.path.exists(path) and os.name == "nt":
            import ctypes
            ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
        return "Century Gothic"
    except Exception:
        return "Segoe UI"

def _make_toggle_photos():
    S = 4
    w, h = 52 * S, 26 * S
    def pill(on):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        body = (234, 168, 66, 255) if on else (205, 188, 148, 255)
        edge = (122, 84, 36, 255)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=(h // 2) - 1,
                            fill=body, outline=edge, width=S)
        kx = (w - h + S) if on else S
        d.ellipse((kx, S, kx + h - 2 * S, h - S),
                  fill=(253, 246, 227, 255), outline=edge, width=max(1, S // 2))
        img = img.resize((52, 26), Image.LANCZOS)
        out = os.path.join(tempfile.gettempdir(), "es_tgl_%s.png" % ("on" if on else "off"))
        img.save(out)
        return out
    return pill(True), pill(False)

SWITCH_W, SWITCH_H = 52, 26

def _focus_existing_window():
    try:
        if os.name != "nt":
            return
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, tr(u"AI Совёнок — настройки"))
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

def _log_window_error(text):
    try:
        from config_loader import user_data_dir
        path = os.path.join(user_data_dir(), "settings_window_error.log")
    except Exception:
        path = os.path.join(BASE_DIR, "settings_window_error.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(u"[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))

def _show_error_box(text):
    if os.name != "nt":
        return
    try:
        import ctypes
        MB_ICONERROR, MB_TOPMOST = 0x10, 0x40000
        ctypes.windll.user32.MessageBoxW(
            None,
            u"Окно настроек AI Совёнок не смогло запуститься.\n\n"
            u"Подробности сохранены в settings_window_error.log.\n\n%s" % text[-800:],
            u"AI Совёнок — ошибка", MB_ICONERROR | MB_TOPMOST)
    except Exception:
        pass

def run_settings_window():
    if _already_running():
        _focus_existing_window()
        return

    if os.name == "nt":
        try:
            import ctypes as _ct
            _ct.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u"ES.AI.Sovyonok.Settings.1")
        except Exception:
            pass

    family = _load_game_font()
    root = tk.Tk()
    _LAST_ROOT[0] = root
    root.title(tr(u"AI Совёнок — настройки"))
    try:
        root.withdraw()
    except Exception:
        pass

    def _report_callback_exception(exc, val, tb):
        import traceback as _tr
        text = "".join(_tr.format_exception(exc, val, tb))
        _log_window_error(u"callback:\n" + text)
    root.report_callback_exception = _report_callback_exception

    try:
        ico = os.path.join(BASE_DIR, "ui", "app_icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
            if os.name == "nt":
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                if hwnd:
                    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
                    hbig = ctypes.windll.user32.LoadImageW(0, ico, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
                    hsmall = ctypes.windll.user32.LoadImageW(0, ico, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hbig)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hsmall)
    except Exception:
        pass

    root.geometry("%sx%s" % (WIN_W, WIN_H))
    root.minsize(MIN_W, MIN_H)
    root.resizable(True, True)
    root.configure(bg="#26402c")

    F = (family, 10)
    FB = (family, 10, "bold")
    FL = (family, 9, "bold")
    FS = (family, 9)
    FT = (family, 18, "bold")
    FTAB = (family, 10, "bold")

    canvas = tk.Canvas(root, highlightthickness=0, bd=0, bg="#26402c", closeenough=2)
    canvas.pack(fill="both", expand=True)

    def measure(text, font):
        return tkfont.Font(root=root, font=font).measure(text)

    _img_cache = {}

    def _to_photo(im):
        return ImageTk.PhotoImage(im)

    def pill(w, h, fill, border, radius=None, shadow=True, gloss=True, bw=1):
        w, h = max(int(w), 6), max(int(h), 6)
        key = (w, h, fill, border, radius, shadow, gloss, bw)
        if key not in _img_cache:
            im, sp = _pill_image(w, h, fill, border, radius, shadow, gloss, bw)
            _img_cache[key] = (_to_photo(im), sp)
        return _img_cache[key]

    PASS = [0]
    MANAGED = []
    I18N_WIDGETS = []
    CLIP_MENUS = []
    hover_count = [0]

    def _set_cursor(on):
        hover_count[0] = max(0, hover_count[0] + (1 if on else -1))
        canvas.config(cursor="hand2" if hover_count[0] else "")

    class Managed(object):
        visible = False
        _pass = -1
        def mark(self):
            self._pass = PASS[0]

    OUT8 = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1), (1, 2))

    class Txt(Managed):
        def __init__(self, text=u"", font=None, fill=CREAM, anchor="w", outline=True,
                     managed=True, justify="left"):
            self.src = text
            shown = tr(text)
            self.outline_ids = []
            if outline:
                for dx, dy in OUT8:
                    sid = canvas.create_text(0, 0, text=shown, font=font or F, fill=OUTLINE,
                                             anchor=anchor, justify=justify, state="hidden")
                    self.outline_ids.append((sid, dx, dy))
            self.id = canvas.create_text(0, 0, text=shown, font=font or F, fill=fill,
                                         anchor=anchor, justify=justify, state="hidden")
            if managed:
                MANAGED.append(self)
            I18N_WIDGETS.append(self)

        def _all(self):
            return [s for s, _, _ in self.outline_ids] + [self.id]

        def place(self, x, y, width=None):
            self.mark()
            for sid, dx, dy in self.outline_ids:
                canvas.coords(sid, x + dx, y + dy)
            canvas.coords(self.id, x, y)
            for i in self._all():
                if width:
                    canvas.itemconfig(i, width=width)
                canvas.itemconfig(i, state="normal")
                canvas.tag_raise(i)
            self.visible = True
            return self

        def hide(self):
            for i in self._all():
                canvas.itemconfig(i, state="hidden")
            self.visible = False

        def set(self, text, fill=None):
            self.src = text
            shown = tr(text if text is not None else u"")
            for i in self._all():
                canvas.itemconfig(i, text=shown)
            if fill:
                canvas.itemconfig(self.id, fill=fill)

        def retranslate(self):
            self.set(getattr(self, "src", u""))

        def bbox(self):
            return canvas.bbox(self.id)

    _seq = [0]

    class Chip(Managed):
        def __init__(self, text, command=None, kind="chip", font=None, h=34, padx=18,
                     min_w=0, dot=None, managed=True):
            _seq[0] += 1
            self.tag = "chip%d" % _seq[0]
            self.src = text
            shown = tr(text)
            self.text, self.command, self.kind = shown, command, kind
            self.font = font or F
            self.h, self.padx, self.min_w, self.dot = h, padx, min_w, dot
            self.nat_w = self._calc_w(shown)
            self.w = self.nat_w
            self.selected = self.hover = False
            self.accent = False
            self.x = self.y = 0
            self.img_id = canvas.create_image(0, 0, anchor="nw", tags=(self.tag,), state="hidden")
            self.dot_id = (canvas.create_oval(0, 0, 8, 8, fill=dot, outline="#5a4020",
                                              tags=(self.tag,), state="hidden") if dot else None)
            self.txt_id = canvas.create_text(0, 0, text=self.text, font=self.font, anchor="center",
                                             tags=(self.tag,), state="hidden")
            canvas.tag_bind(self.tag, "<Enter>", self._enter)
            canvas.tag_bind(self.tag, "<Leave>", self._leave)
            canvas.tag_bind(self.tag, "<ButtonRelease-1>", self._click)
            if managed:
                MANAGED.append(self)
            I18N_WIDGETS.append(self)
            self._paint()

        def _calc_w(self, text):
            return max(self.min_w, measure(text, self.font) + self.padx * 2 + (16 if self.dot else 0))

        def _style(self):
            if self.kind == "primary":
                return "primary_hover" if self.hover else "primary"
            if self.kind == "accent":
                return ("accent_hover" if self.hover else "accent") if self.accent else ("hover" if self.hover else "normal")
            if self.kind == "tab":
                return "tab_selected" if self.selected else ("tab_hover" if self.hover else "tab")
            if self.selected:
                return "selected"
            return "hover" if self.hover else "normal"

        def _paint(self):
            fill, border, fg, shadow = CHIP_STYLES[self._style()]
            ph, sp = pill(self.w, self.h, fill, border, shadow=shadow)
            self.sp = sp
            if ph is not None:
                canvas.itemconfig(self.img_id, image=ph)
            canvas.coords(self.img_id, self.x - sp, self.y - sp)
            canvas.itemconfig(self.txt_id, fill=fg)

        def _enter(self, _e=None):
            self.hover = True
            _set_cursor(True)
            self._paint()

        def _leave(self, _e=None):
            if self.hover:
                _set_cursor(False)
            self.hover = False
            self._paint()

        def _click(self, _e=None):
            if self.hover and self.command:
                self.command()

        def set_text(self, text):
            self.src = text
            shown = tr(text)
            self.text = shown
            self.nat_w = self._calc_w(shown)
            canvas.itemconfig(self.txt_id, text=shown)

        def retranslate(self):
            self.set_text(getattr(self, "src", self.text))

        def set_selected(self, sel):
            if sel != self.selected:
                self.selected = sel
                self._paint()

        def set_accent(self, on):
            if bool(on) != self.accent:
                self.accent = bool(on)
                self._paint()

        def place(self, x, y, w=None):
            self.mark()
            self.x, self.y = int(x), int(y)
            nw = int(w) if w else self.nat_w
            self.w = nw
            self._paint()
            tx = self.x + self.w / 2.0
            cy = self.y + self.h / 2.0
            if self.dot_id:
                tx += 7
                dx = tx - measure(self.text, self.font) / 2.0 - 15
                canvas.coords(self.dot_id, dx, cy - 4, dx + 8, cy + 4)
            canvas.coords(self.txt_id, tx, cy)
            canvas.itemconfig(self.tag, state="normal")
            canvas.tag_raise(self.tag)
            self.visible = True
            return self

        def hide(self):
            if self.hover:
                self._leave()
            canvas.itemconfig(self.tag, state="hidden")
            self.visible = False

    class Field(Managed):
        def __init__(self, widget, padx=12, pady=5, radius=9, icon=None):
            self.widget, self.padx, self.pady, self.radius, self.icon = widget, padx, pady, radius, icon
            self.focus = False
            self.geo = None
            self.img_id = canvas.create_image(0, 0, anchor="nw", state="hidden")
            widget.bind("<FocusIn>", lambda e: self.set_focus(True), add=True)
            widget.bind("<FocusOut>", lambda e: self.set_focus(False), add=True)
            MANAGED.append(self)

        def _paint(self):
            if not self.geo:
                return
            x, y, w, h = self.geo
            fill = (PARCH_FOCUS if self.focus else PARCH) + (255,)
            border = (214, 146, 46, 255) if self.focus else PARCH_EDGE
            ph, sp = pill(w, h, fill, border, radius=self.radius, gloss=False, bw=2 if self.focus else 1)
            if ph is not None:
                canvas.itemconfig(self.img_id, image=ph)
            canvas.coords(self.img_id, x - sp, y - sp)
            bgc = PARCH_FOCUS_HEX if self.focus else PARCH_HEX
            try:
                self.widget.config(bg=bgc)
                if self.icon is not None:
                    self.icon.config(bg=bgc)
            except tk.TclError:
                pass

        def set_focus(self, on):
            self.focus = on
            self._paint()

        def place(self, x, y, w, h):
            self.mark()
            self.geo = (int(x), int(y), int(w), int(h))
            self._paint()
            canvas.itemconfig(self.img_id, state="normal")
            iw = 0
            if self.icon is not None:
                iw = 30
                self.icon.place(in_=canvas, x=x + w - 8 - 22, y=y + (h - 22) // 2, width=22, height=22)
                self.icon.lift()
            self.widget.place(in_=canvas, x=x + self.padx, y=y + self.pady,
                              width=w - self.padx * 2 - iw, height=h - self.pady * 2)
            self.visible = True
            return self

        def hide(self):
            canvas.itemconfig(self.img_id, state="hidden")
            self.widget.place_forget()
            if self.icon is not None:
                self.icon.place_forget()
            self.visible = False

        def screen_rect(self):
            x, y, w, h = self.geo
            return canvas.winfo_rootx() + x, canvas.winfo_rooty() + y, w, h

    class Slider(Managed):
        def __init__(self, var, lo, hi, step, on_change=None):
            _seq[0] += 1
            self.tag = "sld%d" % _seq[0]
            self.var, self.lo, self.hi, self.step, self.on_change = var, lo, hi, step, on_change
            self.edge = canvas.create_line(0, 0, 1, 0, width=10, capstyle="round", fill="#4a3519",
                                           tags=(self.tag,), state="hidden")
            self.track = canvas.create_line(0, 0, 1, 0, width=7, capstyle="round", fill=PARCH_HEX,
                                            tags=(self.tag,), state="hidden")
            self.fill = canvas.create_line(0, 0, 1, 0, width=7, capstyle="round", fill="#eaa842",
                                           tags=(self.tag,), state="hidden")
            ph, _sp = pill(22, 22, (255, 247, 228, 255), HONEY_EDGE, bw=2)
            self.knob = canvas.create_image(0, 0, image=ph, tags=(self.tag,), state="hidden")
            self.x0 = self.x1 = self.cy = 0
            canvas.tag_bind(self.tag, "<Button-1>", self._drag)
            canvas.tag_bind(self.tag, "<B1-Motion>", self._drag)
            canvas.tag_bind(self.tag, "<Enter>", lambda e: _set_cursor(True))
            canvas.tag_bind(self.tag, "<Leave>", lambda e: _set_cursor(False))
            MANAGED.append(self)

        def _drag(self, e):
            if self.x1 <= self.x0:
                return
            frac = min(1.0, max(0.0, (e.x - self.x0) / float(self.x1 - self.x0)))
            v = self.lo + frac * (self.hi - self.lo)
            v = round(round(v / self.step) * self.step, 2)
            self.var.set(v)
            self.redraw()
            if self.on_change:
                self.on_change(v)

        def redraw(self):
            v = float(self.var.get())
            frac = (v - self.lo) / float(self.hi - self.lo)
            kx = self.x0 + frac * (self.x1 - self.x0)
            canvas.coords(self.edge, self.x0, self.cy, self.x1, self.cy)
            canvas.coords(self.track, self.x0, self.cy, self.x1, self.cy)
            canvas.coords(self.fill, self.x0, self.cy, kx, self.cy)
            canvas.coords(self.knob, kx, self.cy + 1)

        def place(self, x, y, w, h=34):
            self.mark()
            self.x0, self.x1, self.cy = x + 11, x + w - 11, y + h / 2.0
            self.redraw()
            canvas.itemconfig(self.tag, state="normal")
            canvas.tag_raise(self.tag)
            self.visible = True

        def hide(self):
            canvas.itemconfig(self.tag, state="hidden")
            self.visible = False

    def attach_clipboard_menu(w):
        m = tk.Menu(w, tearoff=0, bg=PARCH_HEX, fg=INK, activebackground="#eaa842",
                    activeforeground=INK_ON_HONEY, bd=1, font=F)
        is_text = isinstance(w, tk.Text)
        clip_labels = [u"Вырезать", u"Копировать", u"Вставить", u"Выделить всё"]
        m.add_command(label=tr(clip_labels[0]), command=lambda: w.event_generate("<<Cut>>"))
        m.add_command(label=tr(clip_labels[1]), command=lambda: w.event_generate("<<Copy>>"))
        m.add_command(label=tr(clip_labels[2]), command=lambda: w.event_generate("<<Paste>>"))
        m.add_separator()
        m.add_command(label=tr(clip_labels[3]),
                      command=lambda: (w.tag_add("sel", "1.0", "end") if is_text else w.select_range(0, "end")))

        def popup(e):
            try:
                m.tk_popup(e.x_root, e.y_root)
            finally:
                m.grab_release()
        w.bind("<Button-3>", popup)
        CLIP_MENUS.append((m, clip_labels, (0, 1, 2, 4)))

        def hotkeys(e):
            if not (e.state & 0x0004):
                return
            code = e.keycode
            if code == 86:
                w.event_generate("<<Paste>>")
                return "break"
            if code == 67:
                w.event_generate("<<Copy>>")
                return "break"
            if code == 88:
                w.event_generate("<<Cut>>")
                return "break"
            if code == 65:
                if is_text:
                    w.tag_add("sel", "1.0", "end")
                else:
                    w.select_range(0, "end")
                return "break"
        w.bind("<Control-KeyPress>", hotkeys, add=True)

    def make_entry(variable, show=None, justify="left"):
        e = tk.Entry(root, textvariable=variable, show=show or "", font=F, bg=PARCH_HEX, fg=INK,
                     insertbackground=INK, relief="flat", bd=0, highlightthickness=0,
                     disabledbackground=PARCH_HEX, disabledforeground=INK_SOFT,
                     selectbackground="#eaa842", selectforeground=INK_ON_HONEY, justify=justify)
        attach_clipboard_menu(e)
        return e

    def field(variable, show=None, justify="left", icon=None):
        return Field(make_entry(variable, show, justify), icon=icon)

    q = queue.Queue()
    result_txt = {}

    def show_result(kind, msg):
        msg = msg or u""
        color = OK_GREEN if msg.startswith(u"✓") else (ERR_RED if msg.startswith(u"✗") else HINT)
        if kind == "deps":
            set_status(msg, ok=(True if msg.startswith(u"✓") else (False if msg.startswith(u"✗") else None)))
        elif kind in result_txt:
            result_txt[kind].set(msg, color)

    def poll_queue():
        try:
            while True:
                kind, msg = q.get_nowait()
                if kind == "models":
                    models_arrived(msg)
                    continue
                if kind == "lookup":
                    lookup_arrived(msg)
                    continue
                show_result(kind, msg)
        except queue.Empty:
            pass
        root.after(120, poll_queue)

    def bg(kind, fn):
        def worker():
            try:
                q.put((kind, fn()))
            except Exception as e:
                q.put((kind, tr(u"✗ Ошибка: %s") % e))
        threading.Thread(target=worker, daemon=True).start()

    prov_display = {"groq": "Groq", "mistral": "Mistral", "openrouter": "OpenRouter",
                    "openai": "OpenAI", "vsegpt": "VseGPT", "proxyapi": "ProxyAPI",
                    "nvidia": "NVIDIA", "cohere": "Cohere", "github": "GitHub",
                    "ollama": "Ollama", "lmstudio": "LM Studio", "custom": "Свой"}
    llm_cfg = cfg.setdefault("llm", {})
    tts_cfg = cfg.setdefault("tts", {})
    stt_cfg = cfg.setdefault("stt", {})

    llm_provider_var = tk.StringVar(value=prov_display.get(llm_cfg.get("provider", "groq"), "Groq"))
    url_var = tk.StringVar(value=llm_cfg.get("api_url", ""))
    model_var = tk.StringVar(value=llm_cfg.get("model", ""))
    max_tokens_var = tk.StringVar(value=str(llm_cfg.get("max_tokens", 400)))
    temperature_var = tk.DoubleVar(value=float(llm_cfg.get("temperature", 0.9)))
    key_vars = {name: tk.StringVar(value=keys.get(name, "")) for name in ALL_KEYS}
    no_key_var = tk.StringVar(value=u"не нужен — локальный сервер")
    tts_var = tk.StringVar(value={v: k for k, v in TTS_MAP.items()}.get(tts_cfg.get("provider", "auto"), "Авто"))
    custom_tts_var = tk.StringVar(value=tts_cfg.get("custom_tts_url", ""))
    fish_voice_var = tk.StringVar(value=tts_cfg.get("fish_voice_female") or tts_cfg.get("fish_reference_id") or "6dc11f3f67a543f6ad4537a4a347e224")
    fish_voice_m_var = tk.StringVar(value=tts_cfg.get("fish_voice_male", ""))
    fish_model_var = tk.StringVar(value=tts_cfg.get("fish_model") or "s2.1-pro-free")
    el_voice_var = tk.StringVar(value=tts_cfg.get("elevenlabs_voice_female") or tts_cfg.get("elevenlabs_default_voice", ""))
    el_voice_m_var = tk.StringVar(value=tts_cfg.get("elevenlabs_voice_male", ""))
    el_model_var = tk.StringVar(value=tts_cfg.get("elevenlabs_model", "eleven_multilingual_v2"))
    oa_model_var = tk.StringVar(value=tts_cfg.get("openai_tts_model", "tts-1"))
    oa_voice_var = tk.StringVar(value=tts_cfg.get("openai_voice_female") or tts_cfg.get("openai_default_voice") or "nova")
    oa_voice_m_var = tk.StringVar(value=tts_cfg.get("openai_voice_male") or "onyx")
    edge_f_var = tk.StringVar(value=tts_cfg.get("edge_voice_female") or "ru-RU-SvetlanaNeural")
    edge_m_var = tk.StringVar(value=tts_cfg.get("edge_voice_male") or "ru-RU-DmitryNeural")
    sapi_voice_var = tk.StringVar(value=tts_cfg.get("sapi_voice_female") or tts_cfg.get("sapi_voice", ""))
    sapi_voice_m_var = tk.StringVar(value=tts_cfg.get("sapi_voice_male", ""))
    cu_model_var = tk.StringVar(value=tts_cfg.get("custom_tts_model", "tts-1"))
    cu_voice_f_var = tk.StringVar(value=tts_cfg.get("custom_voice_female") or "nova")
    cu_voice_m_var = tk.StringVar(value=tts_cfg.get("custom_voice_male") or "onyx")
    cameo_on = [cfg.get("cameo_enabled", True) is not False]
    stt_var = tk.StringVar(value={v: k for k, v in STT_MAP.items()}.get(stt_cfg.get("provider", "auto"), "Авто"))
    player_name_var = tk.StringVar(value=(cfg.get("_player_name") or u"Семён"))

    def provider_keyname():
        return LLM_PRESETS[llm_provider_var.get()][2]

    def es_confirm(title, text, ok_text, cancel_text=u"Отмена"):
        title, text, ok_text, cancel_text = tr(title), tr(text), tr(ok_text), tr(cancel_text)
        top = tk.Toplevel(root, bg="#8f6c3c")
        top.title(title)
        top.transient(root)
        top.resizable(False, False)
        res = [False]
        inner = tk.Frame(top, bg=PARCH_HEX)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(inner, text=title, font=(family, 13, "bold"), fg=INK, bg=PARCH_HEX).pack(anchor="w", padx=24, pady=(20, 6))
        tk.Label(inner, text=text, font=F, fg=INK, bg=PARCH_HEX, justify="left", wraplength=380).pack(anchor="w", padx=24)
        row = tk.Frame(inner, bg=PARCH_HEX)
        row.pack(fill="x", padx=24, pady=(20, 20))

        def btn(t, primary, cb):
            b0 = "#eaa842" if primary else "#e6d7b2"
            b1 = "#f6ba58" if primary else "#efe3c4"
            b = tk.Label(row, text=t, font=FB if primary else F, bg=b0, fg=INK_ON_HONEY if primary else INK,
                         padx=18, pady=7, cursor="hand2", highlightthickness=1,
                         highlightbackground="#96601e" if primary else "#92703e")
            b.bind("<Button-1>", lambda e: cb())
            b.bind("<Enter>", lambda e: b.config(bg=b1))
            b.bind("<Leave>", lambda e: b.config(bg=b0))
            return b

        def ok():
            res[0] = True
            top.destroy()

        btn(ok_text, True, ok).pack(side="right")
        btn(cancel_text, False, top.destroy).pack(side="right", padx=(0, 10))
        top.bind("<Escape>", lambda e: top.destroy())
        top.bind("<Return>", lambda e: ok())
        top.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - top.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry("+%d+%d" % (x, y))
        top.grab_set()
        top.focus_set()
        root.wait_window(top)
        return res[0]

    def _settings_snapshot():
        snap = {
            "provider": llm_provider_var.get(), "api_url": url_var.get().strip(),
            "model": model_var.get().strip(), "max_tokens": max_tokens_var.get(),
            "temperature": temperature_var.get(), "ui_lang": ui_lang[0],
            "cameo": bool(cameo_on[0]),
            "tts": tts_var.get(), "custom_tts": custom_tts_var.get().strip(),
            "fish_f": fish_voice_var.get().strip(), "fish_m": fish_voice_m_var.get().strip(),
            "fish_model": fish_model_var.get(), "el_f": el_voice_var.get().strip(),
            "el_m": el_voice_m_var.get().strip(), "el_model": el_model_var.get(),
            "oa_model": oa_model_var.get(), "oa_f": oa_voice_var.get().strip(),
            "oa_m": oa_voice_m_var.get().strip(),
            "edge_f": edge_f_var.get(), "edge_m": edge_m_var.get(),
            "sapi_f": sapi_voice_var.get(), "sapi_m": sapi_voice_m_var.get(),
            "cu_model": cu_model_var.get(), "cu_f": cu_voice_f_var.get().strip(),
            "cu_m": cu_voice_m_var.get().strip(),
            "stt": stt_var.get(),
            "keys": tuple(sorted((n, v.get().strip()) for n, v in key_vars.items())),
        }
        return snap

    def _has_unsaved():
        try:
            return _settings_snapshot() != saved_state[0]
        except Exception:
            return False

    saved_state = [_settings_snapshot()]
    _watch_started = [False]

    def refresh_save_btn():
        try:
            b_save.set_accent(_has_unsaved())
        except Exception:
            pass

    def _watch_settings(*_a):
        if not _watch_started[0]: return
        refresh_save_btn()

    def _start_watch():
        if _watch_started[0]: return
        _watch_started[0] = True
        def _poll():
            refresh_save_btn()
            root.after(700, _poll)
        root.after(700, _poll)
        def _hook(w):
            try:
                w.bind("<KeyRelease>", _watch_settings, add="+")
                w.bind("<<Modified>>", _watch_settings, add="+")
                w.bind("<<ComboboxSelected>>", _watch_settings, add="+")
                w.bind("<ButtonRelease-1>", _watch_settings, add="+")
            except Exception:
                pass
            for ch in w.winfo_children():
                _hook(ch)
        _hook(root)
        for var in (llm_provider_var, url_var, model_var, max_tokens_var, temperature_var,
                    tts_var, custom_tts_var, fish_voice_var, fish_voice_m_var, fish_model_var,
                    el_voice_var, el_voice_m_var, el_model_var, oa_model_var, oa_voice_var,
                    oa_voice_m_var, edge_f_var, edge_m_var, sapi_voice_var, sapi_voice_m_var,
                    cu_model_var, cu_voice_f_var, cu_voice_m_var, stt_var):
            try:
                var.trace_add("write", _watch_settings)
            except Exception:
                pass
        for v in key_vars.values():
            try:
                v.trace_add("write", _watch_settings)
            except Exception:
                pass

    def save_all(notify=True):
        llm_cfg["provider"] = {v: k for k, v in prov_display.items()}[llm_provider_var.get()]
        llm_cfg["api_url"] = url_var.get().strip()
        llm_cfg["model"] = model_var.get().strip()
        try:
            llm_cfg["max_tokens"] = int(max_tokens_var.get())
        except Exception:
            pass
        llm_cfg["temperature"] = round(float(temperature_var.get()), 2)
        if llm_provider_var.get() == u"Свой":
            llm_cfg["custom_api_url"] = url_var.get().strip()
            llm_cfg["custom_model"] = model_var.get().strip()
        cfg["cameo_enabled"] = bool(cameo_on[0])
        cfg["ui_lang"] = ui_lang[0]
        tts_cfg["provider"] = TTS_MAP[tts_var.get()]
        tts_cfg["custom_tts_url"] = custom_tts_var.get().strip()
        tts_cfg["fish_voice_female"] = fish_voice_var.get().strip()
        tts_cfg["fish_voice_male"] = fish_voice_m_var.get().strip()
        tts_cfg["fish_reference_id"] = tts_cfg["fish_voice_female"]
        tts_cfg["fish_model"] = fish_model_var.get().strip() or "s2.1-pro-free"
        tts_cfg["elevenlabs_voice_female"] = el_voice_var.get().strip()
        tts_cfg["elevenlabs_voice_male"] = el_voice_m_var.get().strip()
        tts_cfg["elevenlabs_default_voice"] = tts_cfg["elevenlabs_voice_female"]
        tts_cfg["elevenlabs_model"] = el_model_var.get().strip() or "eleven_multilingual_v2"
        tts_cfg["openai_tts_model"] = oa_model_var.get().strip() or "tts-1"
        tts_cfg["openai_voice_female"] = oa_voice_var.get().strip() or "nova"
        tts_cfg["openai_voice_male"] = oa_voice_m_var.get().strip() or "onyx"
        tts_cfg["openai_default_voice"] = tts_cfg["openai_voice_female"]
        _ef, _em = ui_i18n.EDGE_VOICES.get(ui_lang[0], ui_i18n.EDGE_VOICES["ru"])
        tts_cfg["edge_voice_female"] = edge_f_var.get().strip() or _ef
        tts_cfg["edge_voice_male"] = edge_m_var.get().strip() or _em
        tts_cfg["edge_voice"] = tts_cfg["edge_voice_female"]
        tts_cfg["sapi_voice_female"] = sapi_voice_var.get().strip()
        tts_cfg["sapi_voice_male"] = sapi_voice_m_var.get().strip()
        tts_cfg["sapi_voice"] = tts_cfg["sapi_voice_female"]
        tts_cfg["custom_tts_model"] = cu_model_var.get().strip() or "tts-1"
        tts_cfg["custom_voice_female"] = cu_voice_f_var.get().strip() or "nova"
        tts_cfg["custom_voice_male"] = cu_voice_m_var.get().strip() or "onyx"
        nv = tts_cfg.setdefault("narrator_voice", {})
        nv["edge"] = tts_cfg["edge_voice_female"]
        nv["openai"] = tts_cfg["openai_voice_female"]
        nv["fish"] = tts_cfg["fish_voice_female"]
        nv["elevenlabs"] = tts_cfg["elevenlabs_voice_female"]
        stt_cfg["provider"] = STT_MAP[stt_var.get()]
        for name in key_vars:
            keys[name] = key_vars[name].get().strip()
        config_loader.save_config()
        config_loader.save_keys()
        saved_state[0] = _settings_snapshot()
        refresh_save_btn()
        try:
            _post("/reload")
            if notify:
                set_status(u"сохранено, сервер перечитал конфиг", True)
        except Exception:
            if notify:
                set_status(u"сохранено в файлы (сервер не ответил)", False)

    def test_llm():
        save_all(notify=False)
        url = url_var.get().strip()
        model = model_var.get().strip()
        kn = provider_keyname()
        key = key_vars[kn].get().strip() if kn else ""
        prov = llm_provider_var.get()
        show_result("llm", u"Проверяю %s…" % prov)
        try:
            from llm_client import normalize_chat_url
            url = normalize_chat_url(url)
        except Exception as e:
            url = url.rstrip("/")
            if url and not url.endswith("/chat/completions"):
                url += "/chat/completions"

        def job():
            if not url: return u"✗ Не указан API URL."
            if model in ("", "model-name"): return u"✗ Не выбрана модель — нажми «🔍 Модели» или впиши имя вручную."
            if kn and not key: return u"✗ Нет ключа API для %s — нажми «Получить ключ ↗»." % prov
            body = json.dumps({
                "model": model,
                "messages": [{"role": "system", "content": u"Проверка связи. Ответь ровно одним словом: связь"},
                             {"role": "user", "content": "ping"}],
                "max_tokens": 20, "temperature": 0.2,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            if key: req.add_header("Authorization", "Bearer " + key)
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=40) as resp:
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", "replace")
                    j = json.loads(detail)
                    err = j.get("error") if isinstance(j, dict) else None
                    detail = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or detail
                except Exception:
                    detail = str(e)
                return u"✗ %s ответил HTTP %s: %s" % (prov, e.code, str(detail)[:180])
            except urllib.error.URLError as e:
                host = url.split("/")[2] if "//" in url else url
                return u"✗ Нет соединения с %s (%s)" % (host, e.reason)
            ms = int((time.time() - t0) * 1000)
            try:
                txt = payload["choices"][0]["message"]["content"]
            except Exception:
                return u"✗ Странный ответ: %s" % json.dumps(payload, ensure_ascii=False)[:160]
            return u"✓ %s отвечает за %s мс: «%s»" % (prov, ms, (txt or "").strip()[:80])
        bg("llm", job)

    def test_tts():
        save_all(notify=False)
        show_result("tts", u"Синтезирую…")
        def job():
            path, info = tts_client.synthesize(u"Привет, Семён! Проверка женского голоса.", None, False)
            if not path: return tr(u"✗ TTS: %s") % info
            play_mp3(path)
            return tr(u"✓ Голос готов (%s), играю…") % info
        bg("tts", job)

    def test_tts_male():
        save_all(notify=False)
        show_result("tts", u"Синтезирую мужской голос…")
        def job():
            path, info = tts_client.synthesize(u"Привет, Семён! Проверка мужского голоса.", {"id": "sh", "gender": "m"}, False)
            if not path: return tr(u"✗ TTS: %s") % info
            play_mp3(path)
            return tr(u"✓ Мужской голос готов (%s), играю…") % info
        bg("tts", job)

    def test_stt():
        save_all(notify=False)
        if STT_MAP.get(stt_var.get()) == "winh":
            show_result("stt", u"Скажи фразу — откроется диктовка Windows (Win+H)…")
            def job():
                try:
                    text = stt_client.dictate_windows(max_seconds=12)
                except Exception as e:
                    return u"✗ Win+H: %s" % e
                return tr(u"✓ Диктовка: «%s»") % (text or tr(u"(пусто)"))
            bg("stt", job)
            return
        show_result("stt", u"Говори — пишу 3 секунды…")
        def job():
            try:
                wav = stt_client.record_audio(max_seconds=3)
            except Exception as e:
                return u"✗ Микрофон: %s" % e
            text, info = stt_client.transcribe(wav)
            if text is None: return u"✗ Распознавание: %s" % info
            return tr(u"✓ Распознано (%s): «%s»") % (info, text or tr(u"(тишина)"))
        bg("stt", job)

    def check_deps():
        set_status(u"Проверка встроенных компонентов...")
        def job():
            av_t = tts_client.available_providers()
            av_s = stt_client.available_providers()
            return tr(u"✓ компоненты вшиты: edge-tts %s, микрофон %s") % (
                tr(u"есть") if av_t.get("edge") else tr(u"нет"),
                tr(u"есть") if av_s.get("record") else tr(u"нет"))
        bg("deps", job)

    def export_preset():
        from tkinter import filedialog as _fd
        fname = _fd.asksaveasfilename(
            parent=root, title=tr(u"Куда сохранить пресет"), defaultextension=".json", initialfile=u"ai_sovenok_preset.json",
            filetypes=[(tr(u"Пресет AI Совёнка"), "*.json")])
        if not fname: return
        try:
            data = {"_app": "AI.Sovenok", "_version": 1, "_saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "config": json.loads(json.dumps(cfg)), "keys": json.loads(json.dumps(keys)), "characters": None}
            try:
                from config_loader import user_data_dir as _udd
                cp = os.path.join(_udd(), "es_characters.json")
                if os.path.exists(cp):
                    with open(cp, encoding="utf-8") as f:
                        data["characters"] = json.load(f)
            except Exception:
                pass
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            set_status(tr(u"✓ пресет сохранён (%s) — в файле есть ключи API") % os.path.basename(fname), True)
        except Exception as e:
            set_status(tr(u"✗ экспорт: %s") % e, False)

    def import_preset():
        from tkinter import filedialog as _fd
        fname = _fd.askopenfilename(
            parent=root, title=tr(u"Файл пресета"), filetypes=[(tr(u"Пресет AI Совёнка"), "*.json"), (u"JSON", "*.json")])
        if not fname: return
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or ("config" not in data and "keys" not in data):
                set_status(tr(u"✗ это не файл пресета AI Совёнка"), False)
                return
        except Exception as e:
            set_status(tr(u"✗ импорт: %s") % e, False)
            return
        if not es_confirm(u"Импортировать пресет?", u"Из файла будут заменены настройки, ключи API и промпты персонажей.", u"Импортировать"):
            return
        try:
            new_cfg = data.get("config")
            if isinstance(new_cfg, dict):
                cfg.clear()
                cfg.update(new_cfg)
            new_keys = data.get("keys")
            if isinstance(new_keys, dict):
                for _k, _v in new_keys.items():
                    if isinstance(_v, str): keys[_k] = _v
            chars = data.get("characters")
            if isinstance(chars, dict) and chars.get("characters"):
                try:
                    from config_loader import user_data_dir as _udd
                    with open(os.path.join(_udd(), "es_characters.json"), "w", encoding="utf-8") as f:
                        json.dump(chars, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            config_loader.save_config()
            config_loader.save_keys()
            try:
                _post("/reload")
            except Exception:
                pass
            set_status(tr(u"✓ пресет импортирован — перезапускаю окно…"), True)

            def _respawn():
                global _mutex_sock
                try: root.destroy()
                except Exception: pass
                if _mutex_sock:
                    try: _mutex_sock.close()
                    except: pass
                try:
                    subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "settings.pyw")], cwd=BASE_DIR)
                except Exception: pass
            root.after(400, _respawn)
        except Exception as e:
            set_status(tr(u"✗ импорт: %s") % e, False)

    def clear_history():
        if not es_confirm(u"Очистить историю?", u"История диалогов у всех героинь будет стёрта безвозвратно.", u"Очистить"): return
        set_status(u"очищаю историю…")
        def job():
            try:
                _post("/history/clear", {}, timeout=10)
                return u"✓ история диалогов очищена"
            except Exception as e:
                return u"✗ %s" % e
        bg("deps", job)

    _tgl_on_png, _tgl_off_png = _make_toggle_photos()
    toggle_photos = {"on": tk.PhotoImage(file=_tgl_on_png), "off": tk.PhotoImage(file=_tgl_off_png)}

    class Switch:
        def __init__(self, parent, initial):
            self.on = bool(initial)
            self.lb = tk.Label(parent, image=toggle_photos["on" if self.on else "off"], bg=PARCH_HEX, bd=0, cursor="hand2")
            self.lb.bind("<Button-1>", self._click)

        def _click(self, _e=None):
            self.on = not self.on
            self.lb.config(image=toggle_photos["on" if self.on else "off"])

        def get(self):
            return self.on

    class CanvasSwitch(Managed):
        def __init__(self, initial, command=None):
            _seq[0] += 1
            self.tag = "sw%d" % _seq[0]
            self.on = bool(initial)
            self.command = command
            self.w, self.h = SWITCH_W, SWITCH_H
            self.hover = False
            self.x, self.y = 0, 0
            self.img_id = canvas.create_image(0, 0, anchor="nw", image=toggle_photos["on" if self.on else "off"], tags=(self.tag,), state="hidden")
            canvas.tag_bind(self.tag, "<Enter>", self._enter)
            canvas.tag_bind(self.tag, "<Leave>", self._leave)
            canvas.tag_bind(self.tag, "<ButtonRelease-1>", self._click)
            MANAGED.append(self)

        def _enter(self, _e=None):
            self.hover = True
            _set_cursor(True)

        def _leave(self, _e=None):
            if self.hover: _set_cursor(False)
            self.hover = False

        def _click(self, _e=None):
            if self.hover and self.command: self.command()

        def set_on(self, on):
            self.on = bool(on)
            canvas.itemconfig(self.img_id, image=toggle_photos["on" if self.on else "off"])

        def place(self, x, y):
            self.mark()
            self.x, self.y = int(x), int(y)
            canvas.coords(self.img_id, self.x, self.y)
            canvas.itemconfig(self.img_id, state="normal")
            self.visible = True
            return self

        def hide(self):
            if self.hover: self._leave()
            canvas.itemconfig(self.img_id, state="hidden")
            self.visible = False

    def es_confirm_toggles(title, text, options, ok_text):
        title, text, ok_text = tr(title), tr(text), tr(ok_text)
        options = [(k, tr(lab), d) for k, lab, d in options]
        top = tk.Toplevel(root, bg="#8f6c3c")
        top.title(title)
        top.transient(root)
        top.resizable(False, False)
        res = {"ok": False, "vals": {k: bool(d) for k, _l, d in options}}
        switches = {}

        def on_close():
            res["ok"] = False
            top.destroy()

        inner = tk.Frame(top, bg=PARCH_HEX)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(inner, text=title, font=(family, 13, "bold"), fg=INK, bg=PARCH_HEX).pack(anchor="w", padx=24, pady=(20, 6))
        tk.Label(inner, text=text, font=F, fg=INK, bg=PARCH_HEX, justify="left", wraplength=380).pack(anchor="w", padx=24)
        for key, label, dflt in options:
            row = tk.Frame(inner, bg=PARCH_HEX)
            row.pack(fill="x", padx=24, pady=6)
            sw = Switch(row, res["vals"][key])
            switches[key] = sw
            sw.lb.pack(side="left")
            tk.Label(row, text=label, font=F, fg=INK, bg=PARCH_HEX, justify="left", wraplength=330).pack(side="left", padx=(12, 0))
        row = tk.Frame(inner, bg=PARCH_HEX)
        row.pack(fill="x", padx=24, pady=(20, 20))

        def btn(t, primary, cb):
            b0 = "#eaa842" if primary else "#e6d7b2"
            b1 = "#f6ba58" if primary else "#efe3c4"
            bb = tk.Label(row, text=t, font=FB if primary else F, bg=b0, fg=INK_ON_HONEY if primary else INK,
                          padx=18, pady=7, cursor="hand2", highlightthickness=1, highlightbackground="#96601e" if primary else "#92703e")
            bb.bind("<Button-1>", lambda e: cb())
            bb.bind("<Enter>", lambda e: bb.config(bg=b1))
            bb.bind("<Leave>", lambda e: bb.config(bg=b0))
            return bb

        def ok():
            res["ok"] = True
            for k, sw in switches.items(): res["vals"][k] = sw.get()
            top.destroy()
        btn(ok_text, True, ok).pack(side="right")
        btn(u"Отмена", False, on_close).pack(side="right", padx=(0, 10))
        top.bind("<Escape>", lambda e: on_close())
        top.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - top.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry("+%d+%d" % (x, y))
        top.grab_set()
        top.focus_set()
        root.wait_window(top)
        return res if res["ok"] else None

    def reset_all():
        r = es_confirm_toggles(
            u"Сбросить настройки?",
            u"Выберите, что вернуть к значениям по умолчанию.\n\nПромпты героинь не тронутся.",
            [(u"settings", u"Настройки: провайдер, модель, токены, температура, озвучка, распознавание", True),
             (u"keys", u"Ключи API (будут очищены — вставьте заново)", False)], u"Сбросить")
        if not r: return
        want_settings = r["vals"]["settings"]
        want_keys = r["vals"]["keys"]
        if not want_settings and not want_keys: return

        llm_provider_var.set(DEFAULTS["provider"])
        url, model, _kn = LLM_PRESETS[DEFAULTS["provider"]]
        url_var.set(url)
        model_var.set(model)
        max_tokens_var.set(str(DEFAULTS["max_tokens"]))
        temperature_var.set(DEFAULTS["temperature"])
        temp_val.set(u"%0.2f" % DEFAULTS["temperature"])
        tts_var.set(DEFAULTS["tts"])
        stt_var.set(DEFAULTS["stt"])
        custom_tts_var.set("")
        fish_voice_var.set("6dc11f3f67a543f6ad4537a4a347e224")
        fish_voice_m_var.set("")
        fish_model_var.set("s2.1-pro-free")
        el_voice_var.set("EXAVITQu4vr4xnSDxMaL")
        el_voice_m_var.set("")
        el_model_var.set("eleven_multilingual_v2")
        oa_model_var.set("tts-1")
        oa_voice_var.set("nova")
        oa_voice_m_var.set("onyx")
        _ef, _em = ui_i18n.EDGE_VOICES.get(ui_lang[0], ui_i18n.EDGE_VOICES["ru"])
        edge_f_var.set(_ef)
        edge_m_var.set(_em)
        sapi_voice_var.set("")
        sapi_voice_m_var.set("")
        cu_model_var.set("tts-1")
        cu_voice_f_var.set("nova")
        cu_voice_m_var.set("onyx")
        cameo_on[0] = True
        cameo_sw.set_on(True)
        if want_keys:
            for k in key_vars: key_vars[k].set(u"")
        for r in (llm_refresh, tts_refresh, stt_refresh): r()
        sync_key_field()
        save_all(notify=False)
        set_status(u"Настройки сброшены.", True)
        layout()

    title_t = Txt(u"AI Совёнок — настройки", FT, CREAM, managed=False)
    sub_t = Txt(u"Разговоры с героинями «Совёнка»: нейросеть, голос, микрофон", FS, HINT, managed=False)
    badge_img = canvas.create_image(0, 0, anchor="nw")
    badge_dot = canvas.create_oval(0, 0, 8, 8, fill=DOT_IDLE, outline="#5a4020")
    badge_txt = canvas.create_text(0, 0, text=tr(u"сервер: проверяю…"), font=FS, fill=INK, anchor="w")
    status = {"msg": tr(u"сервер: проверяю…"), "ok": None}

    lang_var = tk.StringVar(value=ui_lang[0])
    lang_btn = Chip(u"Язык/Lang", None, managed=False, h=28, padx=10, font=FS)

    def set_lang(code):
        lang_var.set(code)
        if code == ui_lang[0]: return
        ui_lang[0] = code
        cfg["ui_lang"] = code
        female, male = ui_i18n.EDGE_VOICES[code]
        edge_f_var.set(female)
        edge_m_var.set(male)
        apply_language()
        save_all(notify=False)
        set_status(tr(u"Язык переключён, голоса edge-tts подставлены"), True)

    lang_menu = tk.Menu(root, tearoff=0, bg=PARCH_HEX, fg=INK, activebackground="#eaa842", activeforeground=INK_ON_HONEY, bd=1, font=FS)
    lang_menu.add_radiobutton(label=u"Русский", value="ru", variable=lang_var, command=lambda: set_lang("ru"))
    lang_menu.add_radiobutton(label=u"English", value="en", variable=lang_var, command=lambda: set_lang("en"))

    def post_lang(_e=None):
        try:
            lang_menu.tk_popup(root.winfo_rootx() + int(lang_btn.x), root.winfo_rooty() + int(lang_btn.y) + lang_btn.h)
        finally:
            try: lang_menu.grab_release()
            except Exception: pass

    lang_btn.command = post_lang

    autostart_on = [cfg.get("window_autostart", True) is not False]
    def on_autostart_toggle():
        autostart_on[0] = not autostart_on[0]
        autostart_sw.set_on(autostart_on[0])
        cfg["window_autostart"] = bool(autostart_on[0])
        try: config_loader.save_config()
        except Exception: pass
        set_status(tr(u"окно настроек при запуске игры: включено" if autostart_on[0] else u"окно настроек при запуске игры: выключено"), True)

    autostart_sw = CanvasSwitch(autostart_on[0], on_autostart_toggle)
    autostart_lbl = Txt(u"Открывать окно при запуске игры", FS, HINT, anchor="e")

    def layout_badge(w):
        tw = measure(status["msg"], FS)
        bw, bh = tw + 40, 28
        x, y = w - 24 - bw, 24
        ph, sp = pill(bw, bh, CHIP_STYLES["normal"][0], CHIP_STYLES["normal"][1])
        if ph is not None: canvas.itemconfig(badge_img, image=ph)
        canvas.coords(badge_img, x - sp, y - sp)
        canvas.coords(badge_dot, x + 14, y + bh / 2 - 4, x + 22, y + bh / 2 + 4)
        canvas.coords(badge_txt, x + 30, y + bh / 2)
        for i in (badge_img, badge_dot, badge_txt): canvas.tag_raise(i)
        lx = x - 14 - lang_btn.nat_w
        lang_btn.place(lx, y - 1)
        autostart_sw.place(w - 24 - autostart_sw.w, y + bh + 10)
        autostart_lbl.place(w - 24 - autostart_sw.w - 10, y + bh + 10 + 13)

    def set_status(msg, ok=None):
        msg = tr(msg)
        status["msg"], status["ok"] = msg, ok
        canvas.itemconfig(badge_txt, text=msg)
        canvas.itemconfig(badge_dot, fill=DOT_OK if ok is True else (DOT_ERR if ok is False else DOT_IDLE))
        cw = canvas.winfo_width()
        layout_badge(cw if cw > 10 else WIN_W)

    def refresh_server_status():
        def worker():
            try:
                urllib.request.urlopen(_server_url() + "/health", timeout=2)
                ok = True
            except Exception:
                ok = False
            root.after(0, lambda ok=ok: set_status((tr(u"сервер работает · порт %s") % _server_port()) if ok else tr(u"сервер не запущен — настройки сохранятся в файлы"), ok))
        threading.Thread(target=worker, daemon=True).start()

    cur_tab = [0]
    tab_bar_img = canvas.create_image(0, 0, anchor="nw")

    def switch_tab(idx):
        close_models()
        cur_tab[0] = idx
        for i, t in enumerate(tabs): t.set_selected(i == idx)
        if idx == 4 and hist_targets and not hist_loaded[0]:
            hist_loaded[0] = True
            hist_idx[0] = 0
            for j, c in enumerate(hist_chips): c.set_selected(j == 0)
            load_hist(hist_targets[0][0])
        layout()

    tabs = [Chip(n, (lambda i=i: switch_tab(i)), kind="tab", font=FTAB, h=32, padx=10, managed=False)
            for i, n in enumerate([u"Нейросеть", u"Голос", u"Микрофон", u"Промпты", u"История", u"Карта"])]
    tabs[0].set_selected(True)

    def label(text, fill=LABEL, font=None):
        return Txt(text, font or FL, fill)

    def chip_row(names, var, on_change=None, dots=None):
        chips = []
        def refresh():
            for c in chips: c.set_selected(var.get() == getattr(c, "src", c.text))
        for n in names:
            c = Chip(n, None, dot=(dots or {}).get(n))
            c.command = (lambda n=n: (var.set(n), refresh(), on_change and on_change()))
            chips.append(c)
        refresh()
        return chips, refresh

    def flow(chips, x0, y, max_w, gap=8, row_gap=10):
        x, h = x0, 0
        for c in chips:
            if x > x0 and x + c.nat_w > x0 + max_w:
                x, y = x0, y + h + row_gap
            c.place(x, y)
            x += c.nat_w + gap
            h = max(h, c.h)
        return y + h

    H = 34
    LBL = 20
    ROW = LBL + H + 16

    def key_link_chip(kn_getter):
        return Chip(u"Получить ключ ↗", lambda: webbrowser.open(KEY_URLS.get(kn_getter()) or "", new=1))

    # --- Вкладка LLM ---
    llm_sec = label(u"ПРОВАЙДЕР", SECTION)
    def on_provider_change():
        name = llm_provider_var.get()
        url, model, kn = LLM_PRESETS[name]
        if name == u"Свой":
            url_var.set(llm_cfg.get("custom_api_url") or url)
            model_var.set(llm_cfg.get("custom_model") or model)
        else:
            url_var.set(url)
            model_var.set(model)
        sync_key_field()
        close_models()
        layout()

    llm_chips, llm_refresh = chip_row(LLM_PROVIDERS, llm_provider_var, on_provider_change)
    url_l = label(u"API URL")
    url_f = field(url_var)
    key_l = label(u"КЛЮЧ API")
    key_hint = Txt(u"хранится в keys.json, не в конфиге", FS, HINT, anchor="e")
    key_entry = make_entry(key_vars.get(provider_keyname()) or no_key_var, show="•")
    key_f = Field(key_entry)
    key_link = key_link_chip(provider_keyname)

    def sync_key_field():
        kn = provider_keyname()
        if kn:
            key_entry.config(state="normal", textvariable=key_vars[kn], show="•")
        else:
            key_entry.config(textvariable=no_key_var, show="", state="disabled")
    sync_key_field()

    model_l = label(u"МОДЕЛЬ")
    mag_photo = _to_photo(_magnifier_image())
    mag_photo_f = _to_photo(_magnifier_image(bg=PARCH_FOCUS))
    mag_icon = tk.Label(root, image=mag_photo, bg=PARCH_HEX, fg=INK, bd=0, cursor="hand2")
    model_entry = make_entry(model_var)
    model_f = Field(model_entry, icon=mag_icon)
    model_hint = Txt(u"лупа — список моделей провайдера", FS, HINT, anchor="e")

    tok_l = label(u"МАКС. ТОКЕНОВ")
    def tok_step(d):
        try: v = int(max_tokens_var.get())
        except Exception: v = 400
        max_tokens_var.set(str(min(8000, max(50, v + d))))
    tok_minus = Chip(u"−", lambda: tok_step(-50), padx=0, min_w=H, font=FB)
    tok_plus = Chip(u"+", lambda: tok_step(50), padx=0, min_w=H, font=FB)
    tok_f = field(max_tokens_var, justify="center")

    temp_l = label(u"ТЕМПЕРАТУРА · ФАНТАЗИЯ")
    temp_val = Txt(u"%0.2f" % temperature_var.get(), FB, SECTION, anchor="e")
    temp_sl = Slider(temperature_var, 0.1, 1.5, 0.05, on_change=lambda v: temp_val.set(u"%0.2f" % v))
    llm_test = Chip(u"Проверить связь", test_llm, font=FB, padx=22)
    result_txt["llm"] = Txt(u"", FS, HINT)

    def lay_llm(x0, x1, y, bottom):
        cw = x1 - x0
        llm_sec.place(x0, y + 8)
        y = flow(llm_chips, x0, y + LBL + 2, cw) + 22
        url_l.place(x0, y + 8)
        url_f.place(x0, y + LBL, cw, H)
        y += ROW
        key_l.place(x0, y + 8)
        kw = cw
        if provider_keyname():
            key_link.place(x1 - key_link.nat_w, y + LBL)
            kw = cw - key_link.nat_w - 10
            key_hint.place(x0 + kw, y + 8)
        key_f.place(x0, y + LBL, kw, H)
        y += ROW
        tok_w = H + 6 + 90 + 6 + H
        tx = x1 - tok_w
        mw = tx - 24 - x0
        model_l.place(x0, y + 8)
        model_hint.place(x0 + mw, y + 8)
        model_f.place(x0, y + LBL, mw, H)
        tok_l.place(tx, y + 8)
        tok_minus.place(tx, y + LBL)
        tok_f.place(tx + H + 6, y + LBL, 90, H)
        tok_plus.place(tx + H + 6 + 90 + 6, y + LBL)
        y += ROW
        sw = min(440, cw - llm_test.nat_w - 40)
        temp_l.place(x0, y + 8)
        temp_val.place(x0 + sw, y + 8)
        temp_sl.place(x0, y + LBL, sw)
        llm_test.place(x1 - llm_test.nat_w, y + LBL)
        y += ROW
        result_txt["llm"].place(x0, y + 6, width=cw)

    models = {"cache": {}, "top": None, "lb": None, "ids": [], "want": None, "loading": False}
    def models_source():
        prov = llm_provider_var.get()
        url = url_var.get().strip()
        kn = provider_keyname()
        key = key_vars[kn].get().strip() if kn else ""
        murl = MODELS_URLS.get(prov) or (url.split("/chat/completions")[0].rstrip("/") + "/models")
        return murl, key, prov

    def _maybe_autopick_model(ids):
        if ids and model_var.get().strip() in ("", "model-name"): model_var.set(ids[0])

    def _parse_models(payload):
        items = payload
        if isinstance(payload, dict): items = payload.get("data") or payload.get("models") or []
        out = []
        for m in items or []:
            if isinstance(m, str): out.append(m)
            elif isinstance(m, dict):
                mid = m.get("id") or m.get("name")
                if mid: out.append(mid)
        return sorted(set(out), key=lambda s: s.lower())

    def fetch_models(murl, key, prov):
        def job():
            req = urllib.request.Request(murl, headers={"Accept": "application/json"})
            if key: req.add_header("Authorization", "Bearer " + key)
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if prov in FALLBACK_MODELS:
                    return (murl, (u"fallback", list(FALLBACK_MODELS[prov]), u"Список с сервера не получен — показываю стандартный"))
                return (murl, u"✗ список моделей: HTTP %s" % e.code)
            except urllib.error.URLError as e:
                return (murl, u"✗ список моделей: нет соединения (%s)" % e.reason)
            ids = _parse_models(payload)
            if not ids and prov in FALLBACK_MODELS: return (murl, (u"fallback", list(FALLBACK_MODELS[prov]), u"Список пуст — стандартный"))
            return (murl, ids or u"✗ сервер вернул пустой список")
        bg("models", job)

    def models_arrived(msg):
        if not isinstance(msg, tuple):
            show_result("llm", msg)
            return
        murl, res = msg
        models["loading"] = False
        note = None
        if isinstance(res, tuple) and len(res) == 3 and res[0] == u"fallback":
            _, res, note = res
        if isinstance(res, list):
            models["cache"][murl] = res
            if models["want"] == murl:
                models["ids"] = res
                _maybe_autopick_model(res)
                refill_models(show_all=True)
                if note: show_result("llm", note)
        else:
            if models["want"] == murl: close_models()
            show_result("llm", res)

    def open_models():
        if models["top"] is not None:
            close_models()
            return
        if not url_var.get().strip():
            show_result("llm", u"✗ Сначала укажи API URL.")
            return
        murl, key, prov = models_source()
        models["want"] = murl
        _build_dropdown()
        if murl in models["cache"]:
            models["ids"] = models["cache"][murl]
            refill_models(show_all=True)
        else:
            models["ids"] = []
            models["loading"] = True
            _dropdown_message(u"загружаю список моделей…")
            fetch_models(murl, key, prov)
        model_entry.focus_set()

    def _build_dropdown():
        top = tk.Toplevel(root, bg="#8f6c3c")
        top.overrideredirect(True)
        try: top.attributes("-topmost", True)
        except tk.TclError: pass
        wrap = tk.Frame(top, bg=PARCH_HEX)
        wrap.pack(fill="both", expand=True, padx=1, pady=1)
        lb = tk.Listbox(wrap, font=F, bg=PARCH_HEX, fg=INK, bd=0, relief="flat", highlightthickness=0, selectbackground="#eaa842", selectforeground=INK_ON_HONEY, activestyle="none", exportselection=False)
        sb = tk.Scrollbar(wrap, orient="vertical", command=lb.yview, width=10, bg=PARCH_HEX, troughcolor="#e6d7b2", bd=0, relief="flat")
        lb.config(yscrollcommand=sb.set)
        models["sb"] = sb
        lb.pack(side="left", fill="both", expand=True, padx=(8, 2), pady=6)
        lb.bind("<ButtonRelease-1>", lambda e: choose_model())
        lb.bind("<Return>", lambda e: choose_model())
        lb.bind("<Escape>", lambda e: (close_models(), model_entry.focus_set()))
        lb.bind("<Motion>", lambda e: (lb.selection_clear(0, "end"), lb.selection_set(lb.nearest(e.y))))
        models["top"], models["lb"] = top, lb
        position_models()

    def position_models(rows=None):
        top = models["top"]
        if top is None or not model_f.geo: return
        x, y, w, h = model_f.screen_rect()
        n = rows if rows is not None else (models["lb"].size() if models["lb"] else 1)
        lh = tkfont.Font(root=root, font=F).metrics("linespace") + 3
        hh = min(9, max(1, n)) * lh + 14
        sb = models.get("sb")
        if sb is not None:
            try:
                if n > 9 and not sb.winfo_ismapped(): sb.pack(side="right", fill="y", pady=4, before=models["lb"])
                elif n <= 9 and sb.winfo_ismapped(): sb.pack_forget()
            except tk.TclError: pass
        top.geometry("%dx%d+%d+%d" % (w, hh, x, y + h + 4))

    def _dropdown_message(text):
        lb = models["lb"]
        if lb is None: return
        lb.delete(0, "end")
        lb.insert("end", u"  " + text)
        lb.itemconfig(0, fg=INK_SOFT, selectbackground=PARCH_HEX, selectforeground=INK_SOFT)
        position_models(1)

    def refill_models(show_all=False):
        lb = models["lb"]
        if lb is None or models["loading"]: return
        ids = models["ids"]
        cur = model_var.get().strip()
        flt = "" if (show_all or cur in ids) else cur.lower()
        items = [m for m in ids if flt in m.lower()]
        lb.delete(0, "end")
        if not items:
            _dropdown_message(u"нет совпадений — можно вписать вручную")
            return
        for m in items: lb.insert("end", m)
        if cur in items:
            i = items.index(cur)
            lb.selection_set(i)
            lb.see(i)
        position_models(len(items))

    def choose_model():
        lb = models["lb"]
        if lb is None or models["loading"]: return
        sel = lb.curselection()
        if sel:
            val = lb.get(sel[0])
            if val.startswith(u"  "): return
            model_var.set(val)
            model_entry.icursor("end")
        close_models()
        model_entry.focus_set()

    def close_models(_e=None):
        if models["top"] is not None:
            try: models["top"].destroy()
            except tk.TclError: pass
        models["top"] = models["lb"] = models["sb"] = None
        models["want"] = None

    def on_model_key(e):
        if e.keysym in ("Down",):
            if models["top"] is None: open_models()
            elif models["lb"] is not None and models["lb"].size():
                lb = models["lb"]
                lb.focus_set()
                if not lb.curselection(): lb.selection_set(0)
            return "break"
        if e.keysym == "Escape":
            close_models()
            return "break"
        if e.keysym in ("Return", "Up", "Left", "Right", "Home", "End", "Tab"): return
        if models["top"] is not None: root.after(1, refill_models)

    model_entry.bind("<KeyPress>", on_model_key, add=True)
    mag_icon.bind("<Button-1>", lambda e: open_models())
    mag_icon.bind("<Enter>", lambda e: mag_icon.config(image=mag_photo_f))
    mag_icon.bind("<Leave>", lambda e: mag_icon.config(image=mag_photo))

    lookup_icons = set()
    def _outside_click(e):
        if e.widget in (mag_icon, model_entry) or e.widget in lookup_icons: return
        close_models()
        close_lookup()
    root.bind("<Button-1>", _outside_click, add=True)
    root.bind("<Configure>", lambda e: position_models() if e.widget is root else None, add=True)
    root.bind("<Unmap>", lambda e: close_models() if e.widget is root else None, add=True)

    lookup = {"top": None, "lb": None, "sb": None, "field": None, "entry": None, "var": None, "pairs": [], "shown": [], "loading": False, "token": 0}

    def _json_get(url, headers):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def load_fish_models(_query):
        return [
            (u"s2.1-pro", "s2.1-pro"), (u"s2.1-pro-free — бесплатный тариф", "s2.1-pro-free"),
            (u"s2-pro", "s2-pro"), (u"s1", "s1"), (u"drama-3-preview", "drama-3-preview"),
            (u"speech-1.6 — прежнее имя, если уже работает", "speech-1.6"), (u"speech-1.5", "speech-1.5"),
        ]

    def load_fish_voices(_query):
        key = key_vars["fish_api_key"].get().strip()
        if not key: return u"✗ Нет ключа Fish Audio — сначала вставь ключ."
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        seen = set()
        out = []
        def take(url):
            try: payload = _json_get(url, headers)
            except Exception as e: return u"✗ Fish Audio: %s" % e
            items = payload.get("items") or payload.get("data") or []
            for it in items:
                if not isinstance(it, dict): continue
                vid = it.get("_id") or it.get("id") or ""
                if not vid or vid in seen: continue
                seen.add(vid)
                title = it.get("title") or it.get("name") or vid
                out.append((u"%s  ·  %s" % (title, vid), vid))
            return None
        err = take("https://api.fish.audio/model?self=true&page_size=50")
        if err and not out: return err
        take("https://api.fish.audio/model?page_size=30&language=ru&sort_by=task_count")
        if len(out) < 5: take("https://api.fish.audio/model?page_size=20&sort_by=task_count")
        return out or u"✗ Fish Audio вернул пустой список голосов"

    def load_eleven_voices(_query):
        key = key_vars["elevenlabs_api_key"].get().strip()
        if not key: return u"✗ Нет ключа ElevenLabs."
        headers = {"xi-api-key": key, "Accept": "application/json"}
        try: payload = _json_get("https://api.elevenlabs.io/v1/voices", headers)
        except Exception as e: return u"✗ ElevenLabs: %s" % e
        out = []
        for v in payload.get("voices") or []:
            vid = v.get("voice_id") or ""
            if vid: out.append((u"%s  ·  %s" % (v.get("name") or vid, vid), vid))
        return out or u"✗ пустой список голосов ElevenLabs"

    def load_eleven_models(_query):
        key = key_vars["elevenlabs_api_key"].get().strip()
        if not key: return u"✗ Нет ключа ElevenLabs."
        headers = {"xi-api-key": key, "Accept": "application/json"}
        try: payload = _json_get("https://api.elevenlabs.io/v1/models", headers)
        except Exception as e: return u"✗ ElevenLabs: %s" % e
        out = []
        for m in payload if isinstance(payload, list) else (payload.get("models") or []):
            if m.get("can_do_text_to_speech") is False: continue
            mid = m.get("model_id") or m.get("id") or ""
            if mid: out.append((u"%s  ·  %s" % (m.get("name") or mid, mid), mid))
        return out or u"✗ пустой список моделей ElevenLabs"

    def load_openai_models(_query):
        return [(m, m) for m in ("tts-1", "tts-1-hd", "gpt-4o-mini-tts")]

    def load_openai_voices(_query):
        return [(m, m) for m in ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")]

    def load_edge_voices(_query):
        try:
            import asyncio
            import edge_tts
            voices = asyncio.run(edge_tts.list_voices())
        except Exception as e: return u"✗ edge-tts: %s" % e
        out = []
        for v in voices or []:
            loc = v.get("Locale") or ""
            short = v.get("ShortName") or ""
            if not short: continue
            loc_s = str(loc)
            multi = "Multilingual" in short
            want = "en" if ui_lang[0] == "en" else "ru"
            if not loc_s.startswith(want) and not multi: continue
            gender = v.get("Gender") or loc
            label = u"%s · %s" % (short, gender)
            if multi: label = u"%s · %s · многоязычный" % (short, gender)
            out.append((label, short))
        return out or u"✗ нет голосов edge-tts"

    def load_sapi_voices(_query):
        try:
            import pyttsx3
            eng = pyttsx3.init()
            voices = eng.getProperty("voices") or []
        except Exception as e: return u"✗ SAPI: %s" % e
        out = []
        for v in voices:
            vid = getattr(v, "id", "") or ""
            name = getattr(v, "name", "") or vid
            if vid: out.append((u"%s" % name, vid))
        return out or u"✗ нет голосов Windows"

    def load_custom_models(_query):
        url = custom_tts_var.get().strip()
        if not url: return u"✗ Сначала укажи адрес своего TTS."
        base = url.split("/audio/speech")[0].rstrip("/") if "/audio/speech" in url else url
        if not base.endswith("/models"):
            base = base + "/models" if base.endswith("/v1") else base.rstrip("/") + "/v1/models"
        key = key_vars["custom_tts_api_key"].get().strip()
        headers = {"Accept": "application/json"}
        if key: headers["Authorization"] = "Bearer " + key
        try: payload = _json_get(base, headers)
        except Exception as e: return u"✗ Ошибка: %s" % e
        items = payload.get("data") or payload.get("models") or []
        out = []
        for m in items:
            if isinstance(m, str): out.append((m, m))
            elif isinstance(m, dict):
                mid = m.get("id") or m.get("name") or ""
                if mid: out.append((mid, mid))
        return out or u"✗ сервер вернул пустой список"

    def make_mag_icon():
        icon = tk.Label(root, image=mag_photo, bg=PARCH_HEX, fg=INK, bd=0, cursor="hand2")
        icon.bind("<Enter>", lambda e, ic=icon: ic.config(image=mag_photo_f))
        icon.bind("<Leave>", lambda e, ic=icon: ic.config(image=mag_photo))
        lookup_icons.add(icon)
        return icon

    def lookup_field(var, loader):
        icon = make_mag_icon()
        entry = make_entry(var)
        fld = Field(entry, icon=icon)
        icon.bind("<Button-1>", lambda e, f=fld, en=entry, v=var, ld=loader: open_lookup(f, en, v, ld))
        entry.bind("<Down>", lambda e, f=fld, en=entry, v=var, ld=loader: (open_lookup(f, en, v, ld), "break")[1])
        lookup_icons.add(entry)
        return fld

    def open_lookup(field, entry, var, loader):
        close_models()
        if lookup["top"] is not None and lookup["entry"] is entry:
            close_lookup()
            return
        close_lookup()
        lookup["field"] = field
        lookup["entry"] = entry
        lookup["var"] = var
        lookup["token"] += 1
        token = lookup["token"]
        _build_lookup()
        lookup["loading"] = True
        _lookup_message(u"загружаю список…")
        def job():
            try: res = loader(var.get().strip())
            except Exception as e: res = u"✗ %s" % e
            return (token, res)
        bg("lookup", job)
        try: entry.focus_set()
        except Exception: pass

    def lookup_arrived(msg):
        if not isinstance(msg, tuple) or len(msg) != 2:
            show_result("tts", msg if isinstance(msg, str) else u"✗ странный ответ списка")
            return
        token, res = msg
        if token != lookup["token"] or lookup["top"] is None: return
        lookup["loading"] = False
        if isinstance(res, str):
            close_lookup()
            show_result("tts", res)
            return
        lookup["pairs"] = list(res)
        refill_lookup()

    def _build_lookup():
        top = tk.Toplevel(root, bg="#8f6c3c")
        top.overrideredirect(True)
        try: top.attributes("-topmost", True)
        except tk.TclError: pass
        wrap = tk.Frame(top, bg=PARCH_HEX)
        wrap.pack(fill="both", expand=True, padx=1, pady=1)
        lb = tk.Listbox(wrap, font=F, bg=PARCH_HEX, fg=INK, bd=0, relief="flat", highlightthickness=0, selectbackground="#eaa842", selectforeground=INK_ON_HONEY, activestyle="none", exportselection=False)
        sb = tk.Scrollbar(wrap, orient="vertical", command=lb.yview, width=10, bg=PARCH_HEX, troughcolor="#e6d7b2", bd=0, relief="flat")
        lb.config(yscrollcommand=sb.set)
        lookup["sb"] = sb
        lb.pack(side="left", fill="both", expand=True, padx=(8, 2), pady=6)
        lb.bind("<ButtonRelease-1>", lambda e: choose_lookup())
        lb.bind("<Return>", lambda e: choose_lookup())
        lb.bind("<Escape>", lambda e: close_lookup())
        lb.bind("<Motion>", lambda e: (lb.selection_clear(0, "end"), lb.selection_set(lb.nearest(e.y))))
        lookup["top"], lookup["lb"] = top, lb
        position_lookup()

    def position_lookup(rows=None):
        top = lookup["top"]
        field = lookup["field"]
        if top is None or field is None or not field.geo: return
        x, y, w, h = field.screen_rect()
        n = rows if rows is not None else (lookup["lb"].size() if lookup["lb"] else 1)
        lh = tkfont.Font(root=root, font=F).metrics("linespace") + 3
        hh = min(9, max(1, n)) * lh + 14
        sb = lookup.get("sb")
        if sb is not None:
            try:
                if n > 9 and not sb.winfo_ismapped(): sb.pack(side="right", fill="y", pady=4, before=lookup["lb"])
                elif n <= 9 and sb.winfo_ismapped(): sb.pack_forget()
            except tk.TclError: pass
        top.geometry("%dx%d+%d+%d" % (max(w, 280), hh, x, y + h + 4))

    def _lookup_message(text):
        lb = lookup["lb"]
        if lb is None: return
        lb.delete(0, "end")
        lb.insert("end", u"  " + text)
        lb.itemconfig(0, fg=INK_SOFT, selectbackground=PARCH_HEX, selectforeground=INK_SOFT)
        position_lookup(1)

    def refill_lookup():
        lb = lookup["lb"]
        if lb is None or lookup["loading"]: return
        shown = list(lookup["pairs"])
        lookup["shown"] = shown
        lb.delete(0, "end")
        if not shown:
            _lookup_message(u"нет совпадений — можно вписать вручную")
            return
        for label, _val in shown: lb.insert("end", label)
        position_lookup(len(shown))

    def choose_lookup():
        lb = lookup["lb"]
        if lb is None or lookup["loading"]: return
        sel = lb.curselection()
        if not sel: return
        val = lb.get(sel[0])
        if val.startswith(u"  "): return
        shown = lookup.get("shown") or []
        if sel[0] >= len(shown): return
        lookup["var"].set(shown[sel[0]][1])
        try:
            lookup["entry"].icursor("end")
            lookup["entry"].focus_set()
        except Exception: pass
        close_lookup()

    def close_lookup(_e=None):
        if lookup["top"] is not None:
            try: lookup["top"].destroy()
            except tk.TclError: pass
        lookup["top"] = lookup["lb"] = lookup["sb"] = None
        lookup["loading"] = False

    tts_sec = label(u"ПРОВАЙДЕР ОЗВУЧКИ", SECTION)
    tts_chips, tts_refresh = chip_row(TTS_PROVIDERS, tts_var, lambda: layout())
    el_l = label(u"КЛЮЧ ELEVENLABS")
    el_f = field(key_vars["elevenlabs_api_key"], show="•")
    el_link = key_link_chip(lambda: "elevenlabs_api_key")
    fi_l = label(u"КЛЮЧ FISH AUDIO")
    fi_f = field(key_vars["fish_api_key"], show="•")
    fi_link = key_link_chip(lambda: "fish_api_key")
    fv_l = label(u"ЖЕНСКИЙ ГОЛОС FISH · лупа — reference_id")
    fv_f = lookup_field(fish_voice_var, load_fish_voices)
    fv_ml = label(u"МУЖСКОЙ ГОЛОС FISH · лупа — reference_id")
    fv_mf = lookup_field(fish_voice_m_var, load_fish_voices)
    fm_l = label(u"МОДЕЛЬ FISH · лупа — список")
    fm_f = lookup_field(fish_model_var, load_fish_models)
    el_model_l = label(u"МОДЕЛЬ ELEVENLABS · лупа — список")
    el_model_f = lookup_field(el_model_var, load_eleven_models)
    el_voice_l = label(u"ЖЕНСКИЙ ГОЛОС · ElevenLabs, лупа")
    el_voice_f = lookup_field(el_voice_var, load_eleven_voices)
    el_voice_ml = label(u"МУЖСКОЙ ГОЛОС · ElevenLabs, лупа")
    el_voice_mf = lookup_field(el_voice_m_var, load_eleven_voices)
    oa_l = label(u"КЛЮЧ OPENAI")
    oa_hint = Txt(u"общий с провайдером OpenAI во вкладке «Нейросеть»", FS, HINT, anchor="e")
    oa_f = field(key_vars["openai_api_key"], show="•")
    oa_model_l = label(u"МОДЕЛЬ OPENAI TTS · лупа — список")
    oa_model_f = lookup_field(oa_model_var, load_openai_models)
    oa_voice_l = label(u"ЖЕНСКИЙ ГОЛОС OPENAI · лупа")
    oa_voice_f = lookup_field(oa_voice_var, load_openai_voices)
    oa_voice_ml = label(u"МУЖСКОЙ ГОЛОС OPENAI · лупа")
    oa_voice_mf = lookup_field(oa_voice_m_var, load_openai_voices)
    edge_fl = label(u"ЖЕНСКИЙ ГОЛОС · edge-tts, лупа")
    edge_ff = lookup_field(edge_f_var, load_edge_voices)
    edge_ml = label(u"МУЖСКОЙ ГОЛОС · edge-tts, лупа")
    edge_mf = lookup_field(edge_m_var, load_edge_voices)
    sapi_l = label(u"ЖЕНСКИЙ ГОЛОС WINDOWS · лупа")
    sapi_f = lookup_field(sapi_voice_var, load_sapi_voices)
    sapi_ml = label(u"МУЖСКОЙ ГОЛОС WINDOWS · лупа")
    sapi_mf = lookup_field(sapi_voice_m_var, load_sapi_voices)
    cu_l = label(u"АДРЕС СВОЕГО TTS · OpenAI-совместимый")
    cu_f = field(custom_tts_var)
    cuk_l = label(u"КЛЮЧ СВОЕГО TTS")
    cuk_f = field(key_vars["custom_tts_api_key"], show="•")
    cu_model_l = label(u"МОДЕЛЬ СВОЕГО TTS · лупа — /models")
    cu_model_f = lookup_field(cu_model_var, load_custom_models)
    cu_vf_l = label(u"ЖЕНСКИЙ ГОЛОС СВОЕГО TTS")
    cu_vf = field(cu_voice_f_var)
    cu_vm_l = label(u"МУЖСКОЙ ГОЛОС СВОЕГО TTS")
    cu_vm = field(cu_voice_m_var)
    tts_note = Txt(u"", FS, HINT)
    tts_test = Chip(u"Женский голос", test_tts, font=FB, padx=16)
    tts_test_m = Chip(u"Мужской голос", test_tts_male, font=FB, padx=16)
    result_txt["tts"] = Txt(u"", FS, HINT)

    TTS_NOTES = {
        "auto": u"Авто берёт первый доступный провайдер. У каждого свои женский и мужской голоса — открой его чип.",
        "edge": u"Девушки и рассказчик — женский голос, парни (Шурик, Электроник) — мужской.",
        "fish": u"Девушки — женский reference_id, Шурик и Электроник — мужской. Пустой мужской повторяет женский.",
        "elevenlabs": u"Девушки — женский voice_id, парни — мужской.",
        "openai": u"Девушки — женский голос, парни — мужской.",
        "custom": u"Свой OpenAI-совместимый TTS: женский и мужской голос уходят в поле voice.",
        "sapi": u"SAPI — встроенный голос Windows, работает без интернета.",
        "off": u"Озвучка выключена: героини будут отвечать только текстом.",
    }

    def lay_tts(x0, x1, y, bottom):
        cw = x1 - x0
        tts_sec.place(x0, y + 8)
        y = flow(tts_chips, x0, y + LBL + 2, cw) + 22
        mode = TTS_MAP[tts_var.get()]
        if mode == "elevenlabs":
            el_l.place(x0, y + 8)
            el_link.place(x1 - el_link.nat_w, y + LBL)
            el_f.place(x0, y + LBL, cw - el_link.nat_w - 10, H)
            y += ROW
            el_model_l.place(x0, y + 8)
            el_model_f.place(x0, y + LBL, cw, H)
            y += ROW
            el_voice_l.place(x0, y + 8)
            el_voice_f.place(x0, y + LBL, cw, H)
            y += ROW
            el_voice_ml.place(x0, y + 8)
            el_voice_mf.place(x0, y + LBL, cw, H)
            y += ROW
        elif mode == "fish":
            fi_l.place(x0, y + 8)
            fi_link.place(x1 - fi_link.nat_w, y + LBL)
            fi_f.place(x0, y + LBL, cw - fi_link.nat_w - 10, H)
            y += ROW
            fm_l.place(x0, y + 8)
            fm_f.place(x0, y + LBL, cw, H)
            y += ROW
            fv_l.place(x0, y + 8)
            fv_f.place(x0, y + LBL, cw, H)
            y += ROW
            fv_ml.place(x0, y + 8)
            fv_mf.place(x0, y + LBL, cw, H)
            y += ROW
        elif mode == "openai":
            oa_l.place(x0, y + 8)
            oa_hint.place(x1, y + 8)
            oa_f.place(x0, y + LBL, cw, H)
            y += ROW
            oa_model_l.place(x0, y + 8)
            oa_model_f.place(x0, y + LBL, cw, H)
            y += ROW
            oa_voice_l.place(x0, y + 8)
            oa_voice_f.place(x0, y + LBL, cw, H)
            y += ROW
            oa_voice_ml.place(x0, y + 8)
            oa_voice_mf.place(x0, y + LBL, cw, H)
            y += ROW
        elif mode == "edge":
            edge_fl.place(x0, y + 8)
            edge_ff.place(x0, y + LBL, cw, H)
            y += ROW
            edge_ml.place(x0, y + 8)
            edge_mf.place(x0, y + LBL, cw, H)
            y += ROW
            tts_note.set(TTS_NOTES.get(mode, u""))
            tts_note.place(x0, y + 8, width=cw)
            y += 36
        elif mode == "sapi":
            sapi_l.place(x0, y + 8)
            sapi_f.place(x0, y + LBL, cw, H)
            y += ROW
            sapi_ml.place(x0, y + 8)
            sapi_mf.place(x0, y + LBL, cw, H)
            y += ROW
            tts_note.set(TTS_NOTES.get(mode, u""))
            tts_note.place(x0, y + 8, width=cw)
            y += 36
        elif mode == "custom":
            cu_l.place(x0, y + 8)
            cu_f.place(x0, y + LBL, cw, H)
            y += ROW
            cuk_l.place(x0, y + 8)
            cuk_f.place(x0, y + LBL, cw, H)
            y += ROW
            cu_model_l.place(x0, y + 8)
            cu_model_f.place(x0, y + LBL, cw, H)
            y += ROW
            cu_vf_l.place(x0, y + 8)
            cu_vf.place(x0, y + LBL, cw, H)
            y += ROW
            cu_vm_l.place(x0, y + 8)
            cu_vm.place(x0, y + LBL, cw, H)
            y += ROW
        else:
            tts_note.set(TTS_NOTES.get(mode, u""))
            tts_note.place(x0, y + 8, width=cw)
            y += 36
        tts_test.place(x0, y + 4)
        tts_test_m.place(x0 + tts_test.nat_w + 8, y + 4)
        result_txt["tts"].place(x0 + tts_test.nat_w + tts_test_m.nat_w + 24, y + 4 + H / 2.0, width=max(40, cw - tts_test.nat_w - tts_test_m.nat_w - 24))

    stt_sec = label(u"РАСПОЗНАВАНИЕ РЕЧИ", SECTION)
    stt_chips, stt_refresh = chip_row(STT_PROVIDERS, stt_var, lambda: layout())
    stt_note = Txt(u"Встроенные компоненты записи уже включены в сборку.", FS, HINT)
    stt_test = Chip(u"Проверить микрофон · 3 сек", test_stt, font=FB, padx=22)
    result_txt["stt"] = Txt(u"", FS, HINT)

    def lay_stt(x0, x1, y, bottom):
        cw = x1 - x0
        stt_sec.place(x0, y + 8)
        y = flow(stt_chips, x0, y + LBL + 2, cw) + 22
        if STT_MAP.get(stt_var.get()) == "winh":
            stt_note.set(u"Не запись с микрофона, а диктовка Windows: фокус в поле и Win+H.")
            stt_test.set_text(u"Проверить Win+H")
        else:
            stt_note.set(u"Обычная аудиозапись микрофоном.")
            stt_test.set_text(u"Проверить микрофон · 3 сек")
        stt_note.place(x0, y + 8, width=cw)
        y += 40
        stt_test.place(x0, y)
        result_txt["stt"].place(x0 + stt_test.nat_w + 16, y + H / 2.0, width=cw - stt_test.nat_w - 16)

    # --- Промпты ---
    chars_path = os.path.join(BASE_DIR, "es_characters.json")
    try:
        from config_loader import user_data_dir
        cp = os.path.join(user_data_dir(), "es_characters.json")
        if os.path.exists(cp): chars_path = cp
    except Exception: pass

    try:
        with open(chars_path, encoding="utf-8") as f:
            prompt_data = json.load(f)
    except Exception:
        prompt_data = {"characters": [], "player": {}}
    prompt_targets = [(c["id"], c["name"], False) for c in prompt_data.get("characters", [])]
    prompt_targets.append(("player", (prompt_data.get("player") or {}).get("name", u"Семён") + u" (ГГ)", True))
    prompt_idx = [0]

    pr_sec = label(u"ПЕРСОНАЖИ", SECTION)
    pr_chips = []
    for i, (tid, name, is_player) in enumerate(prompt_targets):
        col = None
        for c in prompt_data.get("characters", []):
            if c.get("id") == tid: col = c.get("color")
        pr_chips.append(Chip(name, (lambda i=i: prompt_select(i)), dot=col or ES_NAME_COLORS.get(tid, "#eaa842")))
    pn_l = label(u"ИМЯ ГЛАВНОГО ГЕРОЯ")
    pn_f = field(player_name_var)
    persona_l = label(u"ХАРАКТЕР · PERSONA")
    persona_who = Txt(u"", FB, SECTION, anchor="e")
    persona_text = tk.Text(root, font=F, fg=INK, bg=PARCH_HEX, insertbackground=INK, wrap="word", relief="flat", bd=0, highlightthickness=0, padx=4, pady=4, undo=True, spacing2=3, selectbackground="#eaa842", selectforeground=INK_ON_HONEY)
    attach_clipboard_menu(persona_text)
    persona_box = Field(persona_text, padx=12, pady=10, radius=12)
    pr_save = Chip(u"Сохранить промпт", lambda: prompt_save(), font=FB, padx=22)
    result_txt["prompt"] = Txt(u"", FS, HINT)

    def prompt_select(idx):
        prompt_idx[0] = idx
        for i, c in enumerate(pr_chips): c.set_selected(i == idx)
        tid, name, is_player = prompt_targets[idx]
        persona_who.set(name)
        persona_text.delete("1.0", "end")
        if is_player:
            pd = prompt_data.get("player") or {}
            player_name_var.set(pd.get("name", u"Семён"))
            persona_text.insert("1.0", pd.get("persona", ""))
        else:
            persona_text.insert("1.0", prompt_data["characters"][idx].get("persona", ""))
        persona_text.edit_reset()
        show_result("prompt", u"")
        layout()

    def prompt_save():
        tid, name, is_player = prompt_targets[prompt_idx[0]]
        try:
            if is_player:
                prompt_data["player"] = {"id": "player", "name": player_name_var.get().strip() or u"Семён", "persona": persona_text.get("1.0", "end").strip()}
            else:
                for c in prompt_data["characters"]:
                    if c["id"] == tid: c["persona"] = persona_text.get("1.0", "end").strip()
            with open(chars_path, "w", encoding="utf-8") as f:
                json.dump(prompt_data, f, ensure_ascii=False, indent=2)
            try:
                _post("/reload")
                show_result("prompt", u"✓ Сохранено, сервер перечитал персонажей")
            except Exception:
                show_result("prompt", u"✓ Сохранено в файл (сервер не ответил)")
        except Exception as e:
            show_result("prompt", u"✗ %s" % e)

    def toggle_cameo():
        cameo_on[0] = not cameo_on[0]
        cameo_sw.set_on(cameo_on[0])
        cfg["cameo_enabled"] = bool(cameo_on[0])
        try: config_loader.save_config()
        except Exception: pass

    cameo_sw = CanvasSwitch(cameo_on[0], toggle_cameo)
    cameo_lbl = Txt(u"Появления в локациях", F, CREAM)

    def lay_prompt(x0, x1, y, bottom):
        cw = x1 - x0
        cameo_sw.place(x0, y + 4)
        cameo_lbl.place(x0 + cameo_sw.w + 12, y + 4 + cameo_sw.h / 2.0)
        y += cameo_sw.h + 16
        pr_sec.place(x0, y + 8)
        y = flow(pr_chips, x0, y + LBL + 2, cw) + 22
        if prompt_targets[prompt_idx[0]][2]:
            pn_l.place(x0, y + 8)
            pn_f.place(x0, y + LBL, min(360, cw), H)
            y += ROW
        persona_l.place(x0, y + 8)
        persona_who.place(x1, y + 8)
        by = bottom - H
        persona_box.place(x0, y + LBL, cw, max(90, by - 16 - (y + LBL)))
        pr_save.place(x1 - pr_save.nat_w, by)
        result_txt["prompt"].place(x0, by + H / 2.0, width=cw - pr_save.nat_w - 20)

    # --- История ---
    hist_targets = [(tid, name) for tid, name, is_player in prompt_targets if not is_player]
    hist_idx = [0]
    hist_loaded = [False]
    hist_sec = label(u"ПЕРЕПИСКА", SECTION)
    hist_chips = []

    def hist_select(i):
        hist_idx[0] = i
        for j, c in enumerate(hist_chips): c.set_selected(j == i)
        if hist_targets: load_hist(hist_targets[i][0])

    for i, (tid, name) in enumerate(hist_targets):
        col = None
        for c in prompt_data.get("characters", []):
            if c.get("id") == tid: col = c.get("color")
        hist_chips.append(Chip(name, (lambda i=i: hist_select(i)), dot=col or ES_NAME_COLORS.get(tid, "#eaa842")))
    hist_log_l = label(u"ПЕРЕПИСКА · как было, целиком")
    hist_sum_l = label(u"ВЫЖИМКА · в нейронку уходит она, не весь лог")
    hist_log = tk.Text(root, font=F, fg=INK, bg=PARCH_HEX, insertbackground=INK, wrap="word", relief="flat", bd=0, highlightthickness=0, padx=4, pady=4, spacing2=3)
    hist_sum = tk.Text(root, font=F, fg=INK, bg=PARCH_HEX, insertbackground=INK, wrap="word", relief="flat", bd=0, highlightthickness=0, padx=4, pady=4, undo=True, spacing2=3, selectbackground="#eaa842", selectforeground=INK_ON_HONEY)
    attach_clipboard_menu(hist_log)
    attach_clipboard_menu(hist_sum)
    hist_log_box = Field(hist_log, padx=12, pady=10, radius=12)
    hist_sum_box = Field(hist_sum, padx=12, pady=10, radius=12)
    result_txt["hist"] = Txt(u"", FS, HINT)

    def _set_box(widget, text, readonly=False):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text or "")
        widget.config(state="disabled" if readonly else "normal")

    def _fill_hist(data, err=None):
        if err:
            _set_box(hist_log, err, readonly=True)
            _set_box(hist_sum, "")
            show_result("hist", u"")
            return
        name = data.get("name") or u""
        player = player_name_var.get().strip() or u"Семён"
        lines = []
        for m in data.get("messages") or []:
            who = player if m.get("role") == "user" else name
            lines.append(u"%s: %s" % (who, (m.get("content") or "").strip()))
        _set_box(hist_log, u"\n\n".join(lines) or u"Переписки пока нет.", readonly=True)
        _set_box(hist_sum, data.get("summary") or "")
        show_result("hist", tr(u"%s реплик в логе") % len(data.get("messages") or []))

    def load_hist(cid):
        def job():
            try:
                import urllib.parse
                url = _server_url() + "/history?character=" + urllib.parse.quote(cid)
                r = json.loads(urllib.request.urlopen(url, timeout=8).read().decode("utf-8", "replace"))
            except Exception as e:
                err = u"Сервер не отдал историю. Закрой процесс ES AI Server и зайди в мод заново.\n%s" % e
                root.after(0, lambda err=err: _fill_hist(None, err))
                return
            if not r.get("ok"):
                msg = r.get("error") or u"ошибка"
                root.after(0, lambda msg=msg: _fill_hist(None, msg))
                return
            root.after(0, lambda r=r: _fill_hist(r))
        threading.Thread(target=job, daemon=True).start()

    def hist_do_save():
        if not hist_targets: return
        cid = hist_targets[hist_idx[0]][0]
        text = hist_sum.get("1.0", "end").strip()
        show_result("hist", u"сохраняю выжимку…")
        def job():
            try:
                r = _post("/history/summary", {"character": cid, "summary": text}, timeout=15)
            except Exception as e: return u"✗ %s" % e
            if not r.get("ok"): return u"✗ %s" % r.get("error", "")
            return u"✓ Выжимка сохранена. В нейронку пойдёт она, не весь лог."
        bg("hist", job)

    def hist_do_compress():
        if not hist_targets: return
        cid = hist_targets[hist_idx[0]][0]
        show_result("hist", u"сжимаю переписку…")
        def job():
            try: r = _post("/history/compress", {"character": cid}, timeout=90)
            except Exception as e: return u"✗ %s" % e
            if not r.get("ok"): return u"✗ %s" % r.get("error", "")
            summary = r.get("summary") or ""
            root.after(0, lambda: _set_box(hist_sum, summary))
            return u"✓ Выжимка готова"
        bg("hist", job)

    def hist_do_forget():
        if not hist_targets: return
        cid, name = hist_targets[hist_idx[0]]
        if not es_confirm(u"Забыть переписку?", tr(u"Лог и выжимка «%s» будут стёрты.") % name, u"Забыть"): return
        def job():
            try: r = _post("/history/clear", {"character": cid}, timeout=15)
            except Exception as e: return u"✗ %s" % e
            if not r.get("ok"): return u"✗ %s" % r.get("error", "")
            root.after(0, lambda: load_hist(cid))
            return u"✓ Переписка стёрта"
        bg("hist", job)

    hist_compress = Chip(u"Сжать выжимку", hist_do_compress, font=FB, padx=16)
    hist_save = Chip(u"Сохранить выжимку", hist_do_save, font=FB, padx=16)
    hist_forget = Chip(u"Забыть", hist_do_forget, padx=16)

    def lay_hist(x0, x1, y, bottom):
        cw = x1 - x0
        hist_sec.place(x0, y + 8)
        y = flow(hist_chips, x0, y + LBL + 2, cw) + 14
        hist_log_l.place(x0, y + 4)
        result_txt["hist"].place(x0 + 340, y + 4)
        y += 24
        btn_y = bottom - H
        log_h = max(90, int((btn_y - y - 36) * 0.62))
        hist_log_box.place(x0, y, cw, log_h)
        y += log_h + 10
        hist_sum_l.place(x0, y)
        y += 22
        hist_sum_box.place(x0, y, cw, max(64, btn_y - y - 10))
        hist_compress.place(x0, btn_y)
        hist_save.place(x0 + hist_compress.nat_w + 8, btn_y)
        hist_forget.place(x0 + hist_compress.nat_w + hist_save.nat_w + 16, btn_y)

    # --- Подвал ---
    b_hist = Chip(u"Очистить историю", clear_history, h=36, managed=False)
    b_reset = Chip(u"Сбросить всё", reset_all, h=36, managed=False)
    try:
        from config_loader import user_data_dir as _udd
        b_folder = Chip(u"Папка конфигов", lambda: open_folder(_udd()), h=36, managed=False)
    except Exception:
        b_folder = Chip(u"Папка конфигов", lambda: open_folder(BASE_DIR), h=36, managed=False)
    b_export = Chip(u"Экспорт пресета", export_preset, h=36, managed=False)
    b_import = Chip(u"Импорт пресета", import_preset, h=36, managed=False)
    b_deps = Chip(u"Установить компоненты", check_deps, h=36, managed=False)
    b_save = Chip(u"Сохранить и применить", lambda: save_all(), kind="accent", font=FB, h=36, padx=26, managed=False)

    FOOT_LABELS = [
        (u"Очистить историю", u"Сбросить всё", u"Папка конфигов", u"Экспорт пресета", u"Импорт пресета", u"Проверить компоненты"),
        (u"История ✕", u"Сброс", u"Конфиги", u"Экспорт", u"Импорт", u"Компоненты"),
    ]

    bg_state = {"size": (0, 0), "after": None, "photo": None, "item": None}

    def render_bg(w, h):
        photo = None
        png = _compose_background(w, h)
        if png:
            try: photo = tk.PhotoImage(file=png)
            except Exception: photo = None
        if photo is None: return
        bg_state["photo"] = photo
        bg_state["size"] = (w, h)
        cx, cy = max(w // 2, 0), max(h // 2, 0)
        if bg_state["item"] is None:
            bg_state["item"] = canvas.create_image(cx, cy, anchor="center", image=photo)
        else:
            canvas.itemconfig(bg_state["item"], image=photo)
            canvas.coords(bg_state["item"], cx, cy)
        canvas.tag_lower(bg_state["item"])

    def schedule_bg(w, h):
        if bg_state["after"]: root.after_cancel(bg_state["after"])
        bg_state["after"] = root.after(70, lambda: render_bg(w, h))

    # --- Карта ---
    map_state = {"pil": None, "loaded": False, "loc": None, "loc_name": None, "photo": None, "size": (0, 0)}
    map_img_item = canvas.create_image(0, 0, anchor="nw", state="hidden")
    map_dot = canvas.create_oval(0, 0, 0, 0, fill="#e12d2d", outline="#ffffff", width=2, state="hidden")
    map_lbl_bg = canvas.create_rectangle(0, 0, 0, 0, fill="#c0392b", outline="", state="hidden")
    map_lbl = canvas.create_text(0, 0, text=u"Вы здесь", font=(family, 9, "bold"), fill="#ffffff", anchor="c", state="hidden")
    map_hint = Txt(u"", FS, HINT)
    map_attr = Txt(u"Карта © фандом-вики ЕЛ, CC-BY-SA", FS, HINT, anchor="e")

    class MapView(Managed):
        def mark(self):
            self._pass = PASS[0]

        def _hide_items(self):
            for it in (map_img_item, map_dot, map_lbl_bg, map_lbl):
                canvas.itemconfig(it, state="hidden")

        def place(self, x0, x1, y, bottom):
            self.mark()
            self.visible = True
            w = max(10, x1 - x0)
            h = max(10, bottom - y - 22)
            if not map_state["loaded"]:
                map_state["loaded"] = True
                map_state["pil"] = _load_map_pil()
            pil = map_state["pil"]
            if pil is None:
                self._hide_items()
                map_hint.set(u"Не удалось загрузить карту (нет es_ai_map_bg.b64 рядом с модом).")
                map_hint.place(x0, y + 8, width=w)
                return
            scale = min(w / ES_MAP_IMG_W, h / ES_MAP_IMG_H)
            dw, dh = max(1, int(ES_MAP_IMG_W * scale)), max(1, int(ES_MAP_IMG_H * scale))
            if map_state["size"] != (dw, dh):
                map_state["photo"] = _to_photo(pil.resize((dw, dh), Image.LANCZOS))
                map_state["size"] = (dw, dh)
            ox = x0 + (w - dw) // 2
            oy = y
            canvas.itemconfig(map_img_item, image=map_state["photo"], state="normal")
            canvas.coords(map_img_item, ox, oy)
            canvas.tag_raise(map_img_item)
            loc = map_state["loc"]
            pin = ES_MAP_PIN.get(loc)
            if pin:
                cx, cy = ox + pin[0] * scale, oy + pin[1] * scale
                r = 7
                canvas.coords(map_dot, cx - r, cy - r, cx + r, cy + r)
                lname = map_state.get("loc_name") or u""
                canvas.itemconfig(map_lbl, text=(tr(u"Вы здесь") + (u": " + lname if lname else u"")), state="normal")
                canvas.coords(map_lbl, cx, cy - r - 11)
                bb = canvas.bbox(map_lbl)
                if bb:
                    canvas.coords(map_lbl_bg, bb[0] - 5, bb[1] - 2, bb[2] + 5, bb[3] + 2)
                    canvas.itemconfig(map_lbl_bg, state="normal")
                canvas.itemconfig(map_dot, state="normal")
                canvas.tag_raise(map_lbl_bg)
                canvas.tag_raise(map_lbl)
                canvas.tag_raise(map_dot)
                map_hint.hide()
            else:
                for it in (map_dot, map_lbl_bg, map_lbl): canvas.itemconfig(it, state="hidden")
                map_hint.set(tr(u"Локация пока неизвестна — начни разговор в игре.") if not loc else (tr(u"«%s» — вне карты.") % (map_state.get("loc_name") or loc)))
                map_hint.place(x0, bottom - 2, width=w - 240)
            map_attr.place(x1, bottom - 2, width=236)

        def hide(self):
            self._hide_items()
            self.visible = False

    mapview = MapView()
    MANAGED.append(mapview)

    def set_map_loc(loc, name=None):
        if loc != map_state["loc"] or (name is not None and name != map_state.get("loc_name")):
            map_state["loc"] = loc
            if name is not None: map_state["loc_name"] = name
            if cur_tab[0] == 5: layout()

    def poll_map_state():
        if cur_tab[0] == 5:
            def worker():
                loc, name = None, None
                try:
                    r = json.loads(urllib.request.urlopen(_server_url() + "/state", timeout=2).read().decode("utf-8", "replace"))
                    loc, name = r.get("loc"), r.get("loc_name")
                except Exception: pass
                root.after(0, lambda: set_map_loc(loc, name))
            threading.Thread(target=worker, daemon=True).start()
        root.after(1500, poll_map_state)

    def lay_map(x0, x1, y, bottom):
        mapview.place(x0, x1, y, bottom)

    LAYOUTS = [lay_llm, lay_tts, lay_stt, lay_prompt, lay_hist, lay_map]

    def layout(*_):
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        w = cw if cw > 10 else WIN_W
        h = ch if ch > 10 else WIN_H
        PASS[0] += 1
        x0, x1 = 28, w - 28

        title_t.place(x0, 40)
        sub_t.place(x0 + 1, 66)
        layout_badge(w)

        ty = 92
        bar_w = sum(t.nat_w for t in tabs) + 4 * 2 + 4 * (len(tabs) - 1)
        ph, sp = pill(bar_w, 40, CHIP_STYLES["normal"][0], CHIP_STYLES["normal"][1], radius=20)
        if ph is not None: canvas.itemconfig(tab_bar_img, image=ph)
        canvas.coords(tab_bar_img, x0 - sp, ty - sp)
        canvas.tag_raise(tab_bar_img)
        tx = x0 + 4
        for t in tabs:
            t.place(tx, ty + 4)
            tx += t.nat_w + 4

        by = h - 24 - 36
        avail = x1 - x0
        for labels in FOOT_LABELS:
            for b, t in zip((b_hist, b_reset, b_folder, b_export, b_import, b_deps), labels):
                b.set_text(t)
            need = sum(b.nat_w for b in (b_hist, b_reset, b_folder, b_export, b_import, b_deps, b_save)) + 8 * 6 + 28
            if need <= avail: break
        fx = x0
        for b in (b_hist, b_reset, b_folder, b_export, b_import):
            b.place(fx, by)
            fx += b.nat_w + 8
        b_save.place(x1 - b_save.nat_w, by)
        b_deps.place(x1 - b_save.nat_w - 8 - b_deps.nat_w, by)

        LAYOUTS[cur_tab[0]](x0, x1, ty + 58, by - 18)
        for o in MANAGED:
            if o._pass != PASS[0] and o.visible: o.hide()
        position_models()
        if bg_state["size"] != (w, h): schedule_bg(w, h)

    def on_configure(event):
        if event.widget is canvas: layout()
    canvas.bind("<Configure>", on_configure)

    def apply_language():
        root.title(tr(u"AI Совёнок — настройки"))
        for w in I18N_WIDGETS:
            if hasattr(w, "retranslate"): w.retranslate()
        for menu, labels, indices in CLIP_MENUS:
            for idx, lab in zip(indices, labels):
                try: menu.entryconfig(idx, label=tr(lab))
                except Exception: pass
        refresh_server_status()
        layout()

    root.update_idletasks()
    render_bg(WIN_W, WIN_H)
    if prompt_targets: prompt_select(0)
    layout()
    poll_queue()
    refresh_server_status()
    poll_map_state()

    try:
        root.deiconify()
        root.lift()
    except Exception:
        pass

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    _start_watch()
    root.mainloop()

if __name__ == "__main__":
    try:
        run_settings_window()
    except Exception:
        import traceback
        _log_window_error(traceback.format_exc())
        _show_error_box(traceback.format_exc())
        raise
    finally:
        if _LAST_ROOT[0] is not None:
            try: _LAST_ROOT[0].deiconify()
            except Exception: pass

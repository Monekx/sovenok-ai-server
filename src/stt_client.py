# -*- coding: utf-8 -*-
"""STT-слой: запись с микрофона + транскрипция Whisper.

Запись — sounddevice (pip install sounddevice numpy): пишем до max секунд,
останавливаемся раньше, если 1.2 секунды тишины.
Транскрипция — Groq (whisper-large-v3-turbo), OpenAI (whisper-1) или локальный
faster-whisper (если установлен). Провайдер — как в Smart Lolis (GroqProvider).
"""
import io
import json
import os
import uuid
import urllib.error
import urllib.request

from src.config_loader import cfg, keys


def available_providers():
    av = {}
    try:
        import sounddevice  # noqa
        import numpy  # noqa
        av["record"] = True
    except Exception:
        av["record"] = False
    av["groq"] = bool(keys.get("groq_api_key"))
    av["openai"] = bool(keys.get("openai_api_key"))
    av["winh"] = os.name == "nt"
    try:
        import faster_whisper  # noqa
        av["local"] = True
    except Exception:
        av["local"] = False
    return av


def resolve_transcriber():
    pref = cfg.get("stt", {}).get("provider", "auto")
    av = available_providers()
    if pref != "auto":
        return pref if av.get(pref) else None
    for p in ("winh", "groq", "openai", "local"):
        if av.get(p):
            return p
    return None


def record_audio(max_seconds=None, silence_stop=None):
    """Записывает WAV (16 кГц, mono, int16) с микрофона. Возвращает bytes."""
    import wave

    import numpy as np
    import sounddevice as sd

    scfg = cfg.get("stt", {})
    max_seconds = float(max_seconds or scfg.get("max_record_seconds", 8))
    silence_stop = float(silence_stop or scfg.get("silence_stop_seconds", 1.2))
    sr = 16000
    chunk = int(sr * 0.1)

    frames = []
    silence_run = 0.0
    voiced_run = 0.0
    with sd.InputStream(samplerate=sr, channels=1, dtype="int16", blocksize=chunk) as stream:
        import time
        start = time.time()
        while time.time() - start < max_seconds:
            # sd.read возвращает numpy-массив напрямую
            data, overflow = stream.read(chunk)
            frames.append(data.copy())
            rms = float(np.sqrt(np.mean(np.square(data.astype("float32")))))
            if rms < 250:  # тишина
                silence_run += 0.1
            else:
                silence_run = 0.0
                voiced_run += 0.1
            # останавливаемся, если уже что-то сказали и наступила пауза
            if voiced_run > 0.3 and silence_run >= silence_stop:
                break

    audio = b"".join(f.tobytes() for f in frames)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio)
    return buf.getvalue()


def _multipart_wav(wav_bytes, model, language):
    boundary = uuid.uuid4().hex
    parts = []
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n%s\r\n" % (boundary, model)).encode())
    if language:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n%s\r\n" % (boundary, language)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n"
                  "Content-Type: audio/wav\r\n\r\n" % boundary).encode())
    parts.append(wav_bytes)
    parts.append(("\r\n--%s--\r\n" % boundary).encode())
    body = b"".join(parts)
    ctype = "multipart/form-data; boundary=%s" % boundary
    return body, ctype


def _transcribe_http(wav_bytes, url, api_key, model, language):
    body, ctype = _multipart_wav(wav_bytes, model, language)
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + api_key, "Content-Type": ctype,
                                          "User-Agent": "ES-AI-Mod/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return (payload.get("text") or "").strip()


_local_model = None


def _transcribe_local(wav_bytes):
    global _local_model
    from faster_whisper import WhisperModel
    import io
    import wave
    import numpy as np

    if _local_model is None:
        _local_model = WhisperModel("small", device="cpu", compute_type="int8")

    # Читаем wav-байты напрямую в numpy массив, избегая PyAV
    with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
        frames = wf.readframes(wf.getnframes())
        audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        # Передаем массив numpy вместо пути к файлу
        segments, _ = _local_model.transcribe(audio_data, language=cfg.get("stt", {}).get("language", "ru"))
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        return "Ошибка распознавания: %s" % e


def transcribe(wav_bytes):
    scfg = cfg.get("stt", {})
    provider = resolve_transcriber()
    if not provider:
        return None, "stt_disabled"
    lang = scfg.get("language", "ru")
    try:
        if provider == "groq":
            text = _transcribe_http(wav_bytes, "https://api.groq.com/openai/v1/audio/transcriptions",
                                    keys.get("groq_api_key", ""),
                                    scfg.get("groq_whisper_model", "whisper-large-v3-turbo"), lang)
        elif provider == "openai":
            text = _transcribe_http(wav_bytes, "https://api.openai.com/v1/audio/transcriptions",
                                    keys.get("openai_api_key", ""),
                                    scfg.get("whisper_model", "whisper-1"), lang)
        elif provider == "local":
            text = _transcribe_local(wav_bytes)
        else:
            return None, "stt_disabled"
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:
        return None, str(e)
    return text, provider


def _send_win_h():
    """Горячая клавиша диктовки Windows, как в Smart Lolis (Win+H)."""
    import ctypes
    user32 = ctypes.windll.user32
    VK_LWIN = 0x5B
    KEYUP = 0x0002
    user32.keybd_event(VK_LWIN, 0, 0, 0)
    user32.keybd_event(ord("H"), 0, 0, 0)
    user32.keybd_event(ord("H"), 0, KEYUP, 0)
    user32.keybd_event(VK_LWIN, 0, KEYUP, 0)


def dictate_windows(max_seconds=18, idle_stop=1.6):
    """Не Whisper: фокус в поле и Win+H, Windows сама печатает речь.

    Возвращает распознанный текст. Окно почти у верхнего края, чтобы было куда
    попасть диктовке. После паузы диктовка закрывается повторным Win+H.
    """
    if os.name != "nt":
        raise RuntimeError("Win+H работает только в Windows")
    import ctypes
    import time
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = [
        ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    user32.SetFocus.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetCurrentThreadId.restype = ctypes.c_uint
    user32.GetWindowThreadProcessId.restype = ctypes.c_uint

    WS_POPUP = 0x80000000
    WS_VISIBLE = 0x10000000
    WS_CHILD = 0x40000000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    ES_AUTOHSCROLL = 0x0080
    PM_REMOVE = 1

    sw = user32.GetSystemMetrics(0)
    x = max(40, (sw - 520) // 2)
    hinst = kernel32.GetModuleHandleW(None)
    hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW, "Static", "Диктовка",
        WS_POPUP | WS_VISIBLE, x, 36, 520, 46, None, None, hinst, None)
    if not hwnd:
        raise RuntimeError("не удалось открыть поле диктовки")
    edit = user32.CreateWindowExW(
        0, "Edit", "", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
        8, 10, 504, 26, hwnd, None, hinst, None)
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    our_tid = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if fg_tid and fg_tid != our_tid:
            attached = bool(user32.AttachThreadInput(our_tid, fg_tid, True))
        user32.AllowSetForegroundWindow(0xFFFFFFFF)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(edit or hwnd)
        time.sleep(0.12)
        _send_win_h()
        start = time.time()
        last_change = start
        last_text = ""
        msg = ctypes.wintypes.MSG()
        while time.time() - start < float(max_seconds or 18):
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            n = user32.GetWindowTextLengthW(edit) if edit else 0
            buf = ctypes.create_unicode_buffer(max(1, n + 1))
            if edit:
                user32.GetWindowTextW(edit, buf, n + 1)
            text = buf.value or ""
            if text != last_text:
                last_text = text
                last_change = time.time()
            if text.strip() and (time.time() - last_change) >= float(idle_stop or 1.6) and (time.time() - start) > 0.8:
                return text.strip()
            time.sleep(0.05)
        return (last_text or "").strip()
    finally:
        try:
            user32.DestroyWindow(hwnd)
        except Exception:
            pass
        if attached:
            try:
                user32.AttachThreadInput(our_tid, fg_tid, False)
            except Exception:
                pass
        time.sleep(0.08)
        try:
            _send_win_h()
        except Exception:
            pass

import difflib
import threading

import speech_recognition as sr
import pyttsx3


WAKE_WORDS = ("jarvis", "jarvi", "jarvish", "charvis", "jarvus", "jervis", "jarvez")
WAKE_WORD_SIMILARITY = 0.72

LISTEN_TIMEOUT = 3
PHRASE_TIME_LIMIT = 8
AMBIENT_NOISE_DURATION = 1.0

_state_lock = threading.Lock()
_listening_enabled = True
_speaking_enabled = True

_listen_thread = None
_stop_event = None
_recognizer = sr.Recognizer()
_microphone = None
_noise_adjusted = False

_tts_lock = threading.Lock()


def is_listening_enabled():
    with _state_lock:
        return _listening_enabled


def is_speaking_enabled():
    with _state_lock:
        return _speaking_enabled


def set_listening(enabled):
    global _listening_enabled
    with _state_lock:
        _listening_enabled = bool(enabled)


def set_speaking(enabled):
    global _speaking_enabled
    with _state_lock:
        _speaking_enabled = bool(enabled)


def set_voice(enabled):
    set_listening(enabled)
    set_speaking(enabled)


def speak(text):
    if not text or not is_speaking_enabled():
        return
    with _tts_lock:
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"speak() failed: {e}")


def _strip_wake_word(text):
    words = text.split()
    for i, word in enumerate(words):
        cleaned = word.lower().strip(".,!?")
        for alias in WAKE_WORDS:
            if difflib.SequenceMatcher(None, cleaned, alias).ratio() >= WAKE_WORD_SIMILARITY:
                remainder = words[:i] + words[i + 1:]
                return " ".join(remainder).strip()
    return None


def _transcribe(audio):
    try:
        return _recognizer.recognize_google(audio)
    except (sr.UnknownValueError, sr.RequestError):
        return None


def _listen_loop(on_command, stop_event):
    global _microphone, _noise_adjusted

    while not stop_event.is_set():
        if not is_listening_enabled():
            stop_event.wait(timeout=0.2)
            continue

        try:
            if _microphone is None:
                _microphone = sr.Microphone()
        except OSError as e:
            print(f"no microphone available: {e}")
            stop_event.wait(timeout=2.0)
            continue

        try:
            with _microphone as source:
                if not _noise_adjusted:
                    _recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_NOISE_DURATION)
                    _noise_adjusted = True

                while not stop_event.is_set() and is_listening_enabled():
                    try:
                        audio = _recognizer.listen(source, timeout=LISTEN_TIMEOUT, phrase_time_limit=PHRASE_TIME_LIMIT)
                    except sr.WaitTimeoutError:
                        continue

                    text = _transcribe(audio)
                    if not text:
                        continue

                    command = _strip_wake_word(text)
                    if command is None:
                        continue

                    try:
                        on_command(command)
                    except Exception as e:
                        print(f"voice command handler failed: {e}")
        except OSError as e:
            print(f"microphone error: {e}")
            _microphone = None
            _noise_adjusted = False
            stop_event.wait(timeout=2.0)


def start_listening(on_command):
    global _listen_thread, _stop_event
    if _listen_thread is not None and _listen_thread.is_alive():
        return
    _stop_event = threading.Event()
    _listen_thread = threading.Thread(target=_listen_loop, args=(on_command, _stop_event), daemon=True)
    _listen_thread.start()


def stop_listening():
    global _listen_thread, _microphone, _noise_adjusted
    if _stop_event is not None:
        _stop_event.set()
    if _listen_thread is not None:
        _listen_thread.join(timeout=LISTEN_TIMEOUT + 1)
    _listen_thread = None
    _microphone = None
    _noise_adjusted = False


def shutdown():
    stop_listening()
    set_voice(False)

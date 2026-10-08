import re
import time
import difflib
import threading

import speech_recognition as sr
import pyttsx3


WAKE_WORDS = ("jarvis", "jarvi", "jarvish", "charvis", "jarvus", "jervis", "jarvez")
WAKE_WORD_SIMILARITY = 0.72

# idle: short windows so we react fast to the wake word
IDLE_LISTEN_TIMEOUT = 4
# command loop: a bit longer, you're mid-sentence giving orders
CMD_LISTEN_TIMEOUT = 5
PHRASE_TIME_LIMIT = 8
AMBIENT_NOISE_DURATION = 1.0

# how long the command loop waits with no command before dropping back to idle
COMMAND_MODE_TIMEOUT = 25

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


def _greeting():
    h = time.localtime().tm_hour
    if h < 12:
        return "Good morning."
    if h < 18:
        return "Good afternoon."
    return "Good evening."


def _strip_wake_word(text):
    """Return the text AFTER the wake word if one is present, else None.

    '' means the wake word was said alone (bare wake, no inline command).
    A non-empty string means an inline command like 'jarvis open spotify'.
    """
    words = text.split()
    for i, word in enumerate(words):
        cleaned = word.lower().strip(".,!?")
        for alias in WAKE_WORDS:
            if difflib.SequenceMatcher(None, cleaned, alias).ratio() >= WAKE_WORD_SIMILARITY:
                remainder = words[i + 1:]
                return " ".join(remainder).strip()
    return None


def _is_stop(text):
    return re.search(r'\bstop\b', text.lower()) is not None


def _listen_once(source, timeout):
    """One blocking capture + transcription. Returns lowercased text or None."""
    try:
        audio = _recognizer.listen(
            source, timeout=timeout, phrase_time_limit=PHRASE_TIME_LIMIT
        )
    except sr.WaitTimeoutError:
        return None
    try:
        return _recognizer.recognize_google(audio).lower()
    except (sr.UnknownValueError, sr.RequestError):
        return None


def _dispatch(on_command, text):
    try:
        on_command(text)
    except Exception as e:
        print(f"voice command handler failed: {e}")


def _session(on_command, source, stop_event):
    """PHASE 1 idle (wait for wake word) -> PHASE 2 command loop.

    Mirrors the old jarvis.py main_loop: once woken, stay in the command
    loop taking orders WITHOUT the wake word until 'stop' or an idle timeout.
    """
    # ---- PHASE 1: IDLE, wait for wake word ----
    while not stop_event.is_set() and is_listening_enabled():
        text = _listen_once(source, IDLE_LISTEN_TIMEOUT)
        if not text:
            continue

        remainder = _strip_wake_word(text)
        if remainder is None:
            continue  # no wake word this utterance — keep idling

        # ---- wake word heard ----
        speak(_greeting())

        # inline command, e.g. "jarvis open spotify"
        if remainder:
            _dispatch(on_command, remainder)

        # ---- PHASE 2: COMMAND LOOP (no wake word needed) ----
        last_cmd = time.monotonic()
        while not stop_event.is_set() and is_listening_enabled():
            if time.monotonic() - last_cmd > COMMAND_MODE_TIMEOUT:
                break  # went quiet — drop back to idle

            query = _listen_once(source, CMD_LISTEN_TIMEOUT)
            if not query:
                continue

            print(f"You said: {query}")

            if _is_stop(query):
                speak("Command mode off.")
                break  # back to PHASE 1

            last_cmd = time.monotonic()
            _dispatch(on_command, query)
        # loop broke -> fall through to idle again


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
                    _recognizer.adjust_for_ambient_noise(
                        source, duration=AMBIENT_NOISE_DURATION
                    )
                    _noise_adjusted = True
                _session(on_command, source, stop_event)
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
    _listen_thread = threading.Thread(
        target=_listen_loop, args=(on_command, _stop_event), daemon=True
    )
    _listen_thread.start()


def stop_listening():
    global _listen_thread, _microphone, _noise_adjusted
    if _stop_event is not None:
        _stop_event.set()
    if _listen_thread is not None:
        _listen_thread.join(timeout=CMD_LISTEN_TIMEOUT + 1)
    _listen_thread = None
    _microphone = None
    _noise_adjusted = False


def shutdown():
    stop_listening()
    set_voice(False)

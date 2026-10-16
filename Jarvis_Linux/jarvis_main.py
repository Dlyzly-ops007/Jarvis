#!/usr/bin/env python3
"""JARVIS — lightweight Linux prototype. Central coordinator and command router.

Flow:  input (text REPL / voice / -c) -> Jarvis.handle()
         -> pending-choice check ("the second one", "yes")
         -> split_commands()  ("open firefox and check battery" -> 2 units)
         -> Router.dispatch()  (first intent whose pattern fullmatches wins)
         -> handler -> result dict {"ok","text","error","speech"?,"data"?}
         -> _emit(): print text, speak `speech` if voice output is on

Patterns are anchored full matches checked in priority order, so a word
appearing somewhere in a sentence can't hijack a command.
"""
from __future__ import annotations

import argparse
import difflib
import logging
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from capabilities import (AppLauncher, BackgroundMonitor, FileSearch, Network, SystemMonitor,
                          WebSearch, fmt_duration)
from core import PROJECT_DIR, SETTABLE, Settings, config_home, fail, load_dotenv, ok, setup_logging, state_home
from oslayer import PlatformBase, get_platform
from personality import Personality
from voice import Voice

log = logging.getLogger("jarvis.main")
__version__ = "0.1.0"

ON_WORDS = {"on", "enable", "start", "activate", "unmute"}
YES_RE = re.compile(r"(?:yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|please do|y|correct)", re.I)
NO_RE = re.compile(r"(?:no|nope|nah|never ?mind|cancel|forget it|n|stop)", re.I)
ORDINALS = {"first": 1, "1st": 1, "one": 1, "second": 2, "2nd": 2, "two": 2, "third": 3, "3rd": 3,
            "three": 3, "fourth": 4, "4th": 4, "four": 4, "fifth": 5, "5th": 5, "five": 5,
            "sixth": 6, "six": 6, "seventh": 7, "seven": 7, "eighth": 8, "eight": 8,
            "ninth": 9, "nine": 9, "tenth": 10, "ten": 10}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20,
                "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90}
UNIT_SECONDS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60,
                "mins": 60, "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600,
                "hour": 3600, "hours": 3600}
UNITS = r"seconds?|secs?|minutes?|mins?|hours?|hrs?"
KINDS = r"files?|folders?|director(?:y|ies)|documents?|pdfs?|images?|photos?|pictures?|videos?"
EXT_FILTERS = {"pdf": (".pdf",), "image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"),
               "photo": (".jpg", ".jpeg", ".png", ".heic", ".webp"),
               "picture": (".jpg", ".jpeg", ".png", ".gif", ".webp"),
               "video": (".mp4", ".mkv", ".webm", ".avi", ".mov")}
URL_RE = re.compile(r"(?:https?://\S+|(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|dev|gov|edu|in|co|uk|"
                    r"ai|app|me|info|xyz|tv|gg|so|sh|ly|us|ca|de|fr|jp|au)(?:/\S*)?)", re.I)
SITES = {"youtube": "https://www.youtube.com", "github": "https://github.com", "gmail": "https://mail.google.com",
         "reddit": "https://www.reddit.com", "wikipedia": "https://en.wikipedia.org",
         "stackoverflow": "https://stackoverflow.com", "stack overflow": "https://stackoverflow.com",
         "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "google": "https://www.google.com"}
CHAIN_VERBS = {"open", "launch", "start", "run", "find", "locate", "search", "google", "look", "show", "check",
               "tell", "what", "what's", "whats", "how", "notify", "remind", "set", "turn", "switch", "lock",
               "mute", "unmute", "enable", "disable", "list", "scan", "go", "visit", "save", "stop", "get",
               "give", "where", "where's", "send", "exit", "quit", "voice", "wifi", "wi-fi"}


def _friendly_keys() -> list[str]:
    """Settable keys as users type them: last segment, or section name for '<section>.enabled'."""
    return [k.split(".")[0] if k.endswith(".enabled") else k.split(".")[-1] for k in SETTABLE]


# ── routing primitives ─────────────────────────────────────────────────────
@dataclass
class Intent:
    name: str
    patterns: list
    handler: Callable
    priority: int = 50
    examples: tuple = ()
    help: str = ""


def split_commands(text: str, verbs: set[str] = CHAIN_VERBS) -> list[str]:
    """Split a chained utterance into command units.

    ';', 'then' and 'and then' always split. A bare ' and ' splits only when the
    next fragment starts with an action verb, so 'find cats and dogs' stays one
    command while 'open firefox and check battery' becomes two. Reminder and
    notification bodies are never split.
    """
    text = (text or "").strip()
    if not text:
        return []
    body_cmd = re.compile(r"^(?:remind|notify|alert|send (?:me )?(?:a )?notification)\b", re.I)
    units: list[str] = []
    for part in re.split(r"\s*;\s*|,?\s+and then\s+|,?\s+then\s+", text, flags=re.I):
        if not part.strip():
            continue
        pieces = re.split(r",?\s+and\s+", part, flags=re.I)
        cur = pieces[0]
        for nxt in pieces[1:]:
            first = nxt.split()[0].lower() if nxt.split() else ""
            if first in verbs and not body_cmd.match(cur):
                units.append(cur)
                cur = nxt
            else:
                cur = f"{cur} and {nxt}"
        units.append(cur)
    return [u.strip() for u in units if u.strip()]


def parse_choice(text: str, n: int) -> int | None:
    """'2', 'the second one', 'option 3', 'last' -> 0-based index, or None."""
    t = re.sub(r"\b(?:open|the|one|number|option|result|file|choice|app|#|please)\b", " ", text.lower())
    t = t.strip(" .#")
    t = re.sub(r"\s+", " ", t)
    if t == "last" and n:
        return n - 1
    idx = int(t) if t.isdigit() else ORDINALS.get(t)
    if idx is not None and 1 <= idx <= n:
        return idx - 1
    return None


def parse_duration(amount: str, unit: str) -> float | None:
    amount = amount.lower().strip()
    try:
        value = float(amount)
    except ValueError:
        value = NUMBER_WORDS.get(amount)
        if value is None:
            return None
    mult = UNIT_SECONDS.get(unit.lower().rstrip("."))
    return value * mult if mult else None


class Router:
    def __init__(self, wake_words=("jarvis",)):
        self.intents: list[Intent] = []
        self.wake_words = [w.lower() for w in wake_words if w]
        self.on_error: Callable[[str, Exception], dict] = \
            lambda name, e: fail("Something went wrong.", error=f"{type(e).__name__}: {e}")
        self.on_unknown: Callable[[str, str | None], dict] = \
            lambda text, sug: fail("I don't know that one.", error="unknown")

    def add(self, name, patterns, handler, priority=50, examples=(), help=""):
        self.intents.append(Intent(name, [re.compile(p, re.I) for p in patterns], handler,
                                   priority, tuple(examples), help))
        self.intents.sort(key=lambda i: i.priority)       # stable: equal priority keeps order

    def normalize(self, text: str) -> str:
        t = re.sub(r"\s+", " ", (text or "").strip())
        t = re.sub(r"[\s.!?,]+$", "", t)
        if self.wake_words:
            ww = "|".join(map(re.escape, self.wake_words))
            t = re.sub(rf"^(?:(?:hey|ok|okay|yo)[\s,]+)?(?:(?:{ww})\b[\s,:!.]*)", "", t, flags=re.I)
        t = re.sub(r"^(?:(?:please|kindly|can you|could you|would you|will you|i want you to|"
                   r"i need you to|go ahead and|just)\s+)+", "", t, flags=re.I)
        t = re.sub(r"\s+(?:please|for me)$", "", t, flags=re.I)
        return t.strip()

    def match(self, text: str):
        for intent in self.intents:
            for p in intent.patterns:
                m = p.fullmatch(text)
                if m:
                    return intent, m
        return None, None

    def suggest(self, text: str) -> str | None:
        examples = [e for i in self.intents for e in i.examples]
        hit = difflib.get_close_matches(text.lower(), examples, n=1, cutoff=0.72)
        return hit[0] if hit else None

    def dispatch(self, text: str) -> dict:
        norm = self.normalize(text) or "hello"
        intent, m = self.match(norm)
        if intent is None:
            result = self.on_unknown(norm, self.suggest(norm))
            result["intent"] = "unknown"
            return result
        log.info("intent=%s text=%r", intent.name, norm)
        try:
            result = intent.handler(m)
            if not isinstance(result, dict):
                result = ok(str(result or ""))
        except Exception as e:                           # never let a handler kill the loop
            log.exception("handler %s failed", intent.name)
            result = self.on_error(intent.name, e)
        result["intent"] = intent.name
        return result


# ── coordinator ────────────────────────────────────────────────────────────
class Jarvis:
    def __init__(self, settings: Settings, platform: PlatformBase | None = None,
                 voice: Voice | None = None, output: Callable[[str], None] | None = None):
        self.settings = settings
        self.platform = platform or get_platform()
        self.name = str(settings.get("assistant_name") or "Jarvis")
        self.output = output or (lambda text: print(f"{self.name}: {text}", flush=True))
        self.persona = Personality(settings)
        self.apps = AppLauncher(self.platform, settings)
        self.files = FileSearch(self.platform, settings)
        self.system = SystemMonitor(self.platform, settings)
        self.net = Network(self.platform, settings)
        self.web = WebSearch(self.platform, settings)
        self.voice = voice or Voice(settings, on_command=lambda t: self.handle(t, source="voice"),
                                    on_heard=lambda t: self.output(f"(heard) {t}"))
        self.monitor = BackgroundMonitor(self.system, settings, self._on_alert)
        self.router = Router(wake_words=[self.name.lower(), str(settings.get("voice.wake_word") or "")])
        self.router.on_error = lambda name, e: fail(self.persona.line("error"), error=f"{type(e).__name__}: {e}")
        self.router.on_unknown = self._unknown
        self.running = True
        self.pending: dict | None = None
        self.last_results: list[str] = []
        self.reminders: list[dict] = []
        self._lock = threading.RLock()
        self._register_intents()

    # -- lifecycle ------------------------------------------------------
    def start(self, voice_in: bool | None = None, voice_out: bool | None = None,
              greet: bool = True, monitor: bool = True) -> None:
        threading.Thread(target=self.apps.index, name="jarvis-appindex", daemon=True).start()
        want_out = self.settings.get("voice.output_enabled") if voice_out is None else voice_out
        want_in = self.settings.get("voice.input_enabled") if voice_in is None else voice_in
        if want_out:
            r = self.voice.set_output(True)
            if not r["ok"]:
                self.output(r["text"] + " Continuing text-only.")
        if greet and self.settings.get("personality.greet_on_start"):
            self._emit(ok(self.persona.greeting()))
        if want_in:
            r = self.voice.set_input(True)
            self.output(r["text"] + ("" if r["ok"] else " Continuing with text input."))
        if monitor and self.settings.get("monitor.enabled"):
            self.monitor.start()

    def shutdown(self) -> None:
        self.monitor.stop()
        for rem in self.reminders:
            rem["timer"].cancel()
        self.voice.shutdown()
        log.info("shutdown")

    def wait_for_speech(self, timeout: float = 30) -> None:
        end = time.monotonic() + timeout
        time.sleep(0.2)
        while time.monotonic() < end and (self.voice.is_speaking() or not self.voice._q.empty()):
            time.sleep(0.1)

    # -- dispatch -------------------------------------------------------
    def handle(self, text: str, source: str = "text") -> list[dict]:
        """Entry point for every input surface. Returns the results emitted."""
        with self._lock:
            text = (text or "").strip()
            if not text:
                return []
            log.info("input source=%s text=%r", source, text)
            pending = self._resolve_pending(self.router.normalize(text))
            if pending is not None:
                self._emit(pending)
                return [pending]
            results = []
            for unit in split_commands(text):
                r = self.router.dispatch(unit)
                self._emit(r)
                results.append(r)
                if not self.running:
                    break
            return results

    def _emit(self, r: dict) -> None:
        if r.get("text"):
            self.output(r["text"])
        if not r.get("ok") and r.get("error") and r.get("error") != r.get("text"):
            log.info("result error (%s): %s", r.get("intent"), r["error"])
        self.voice.say(r.get("speech", r.get("text", "")))

    def _unknown(self, text: str, suggestion: str | None) -> dict:
        if suggestion:
            self._set_pending("suggestion", [suggestion])
            return fail(self.persona.line("suggest", cmd=suggestion), error="unknown")
        return fail(self.persona.line("unknown"), error="unknown")

    def _set_pending(self, kind: str, options: list, ttl: float = 45) -> None:
        self.pending = {"kind": kind, "options": options, "expires": time.monotonic() + ttl}

    def _resolve_pending(self, text: str) -> dict | None:
        p = self.pending
        if not p:
            return None
        if time.monotonic() > p["expires"]:
            self.pending = None
            return None
        if NO_RE.fullmatch(text):
            self.pending = None
            return ok(self.persona.line("cancel"))
        if p["kind"] == "suggestion":
            self.pending = None
            if YES_RE.fullmatch(text):
                return self.router.dispatch(p["options"][0])
            return None
        if p["kind"] == "app_choice":
            opts = p["options"]
            idx = parse_choice(text, len(opts))
            if idx is None:
                low = text.lower()
                hits = [i for i, e in enumerate(opts) if low and low in e.name.lower()]
                idx = hits[0] if len(hits) == 1 else None
            if idx is None:
                self.pending = None
                return None
            self.pending = None
            r = self.apps.launch_entry(opts[idx])
            if r["ok"]:
                r["text"] = self.persona.line("open", name=opts[idx].name)
            r["intent"] = "app_choice"
            return r
        self.pending = None
        return None

    def _on_alert(self, message: str, urgency: str = "normal") -> None:
        self.output(f"[alert] {message}")
        self.notify(self.name, message, urgency)
        self.voice.say(message)

    def notify(self, title: str, body: str, urgency: str = "normal") -> dict:
        if not self.settings.get("notifications.enabled"):
            return fail("Notifications are turned off in settings.", error="disabled")
        try:
            return self.platform.notify(title, body, urgency, app_name=str(self.settings.get("notifications.app_name")),
                                        timeout_ms=int(self.settings.get("notifications.timeout_ms") or 6000))
        except Exception as e:
            log.exception("notify failed")
            return fail("Notification failed.", error=str(e))

    # -- intent table ---------------------------------------------------
    def _register_intents(self) -> None:
        add = self.router.add
        # Safety first: these must win over anything that looks like "open"/"run".
        add("refuse_privileged",
            [r"(?:sudo|su|pkexec|doas)\b.*",
             r".*(?:\bas root\b|\bwith sudo\b|\broot (?:access|shell|terminal|privileges)\b|\brm\s+-rf\b|"
             r"\bchmod\s+777\b|\bmkfs\b|\bdd\s+if=).*"],
            lambda m: fail(self.persona.line("refuse_privileged"), error="privileged"), 5)
        add("refuse_shell",
            [r"(?:run|execute|exec)\s+(?:the |this |a |that )?(?:shell |terminal |bash |system )?"
             r"(?:command|script|code)\b.*", r"(?:bash|sh|zsh)\s+-c\b.*"],
            lambda m: fail("I don't execute arbitrary shell commands. I can open a terminal for you, though.",
                           error="shell"), 5)
        add("refuse_power",
            [r"(?:shut ?down|power ?off|turn off|reboot|restart|hibernate|suspend|log ?out|sign out)"
             r"(?: the| my| this)?(?: computer| pc| system| machine| laptop| vm| device| session)?"],
            lambda m: fail(self.persona.line("refuse_power"), error="power"), 6)
        add("unported",
            [r"(telegram(?: bot)?|spotify|play (?:the usual|music|some music|.+ on spotify)|game mode(?: on| off)?|"
             r"holographic(?: mode)?|canvas(?: mode)?|lms|cursor scheme|cursor heist|bluetooth(?: on| off)?|"
             r"(?:turn|switch) (?:on|off) bluetooth|(?:take a )?screenshot|ngrok|brief me|timetable|"
             r"what(?:'s| is) on my screen|read (?:the )?screen)"],
            self.h_unported, 7)
        add("exit", [r"(?:exit|quit|bye|goodbye|good ?bye|good night|see you(?: later)?|that'?s all|"
                     r"(?:shut ?down|close|stop|quit|exit|turn off|power down) (?:jarvis|yourself)|go to sleep)"],
            self.h_exit, 8, examples=("exit",), help="exit | goodbye — close Jarvis")
        add("stop", [r"(?:stop|cancel|never ?mind|shh+|hush)"], self.h_stop, 9)

        add("greeting", [r"(?:hi|hello|hey|yo|hiya|what'?s up|sup|good (?:morning|afternoon|evening)|hey there|hello there|"
                         r"wake up|you there|are you there|are you awake)(?: there)?"],
            lambda m: ok(self.persona.greeting()), 20, examples=("hello",))
        add("help", [r"(?:help|commands|what can you do|list commands|show commands|\?|how do i use you)"],
            self.h_help, 20, examples=("help",), help="help — this list")
        add("time", [r"(?:what(?:'s| is)? )?(?:the )?(?:current )?time(?: is it)?(?: now)?(?: right now)?",
                     r"what time is it(?: now)?", r"tell me the time"],
            self.h_time, 20, examples=("what time is it",), help="what time is it | what's the date")
        add("date", [r"(?:what(?:'s| is) )?(?:the |today'?s )?date(?: today)?", r"what day is (?:it|today)",
                     r"what(?:'s| is) (?:the )?day(?: today)?", r"today'?s date"],
            self.h_date, 20, examples=("what's the date", "what day is it"))
        add("thanks", [r"(?:thanks|thank you|thx|cheers|nice|good job|well done|great|perfect)(?: jarvis)?(?: so much)?"],
            lambda m: ok(self.persona.line("thanks")), 25)
        add("how_are_you", [r"how(?:'s| is| are) (?:you|it going|things)(?: doing)?(?: today)?", r"how do you do"],
            lambda m: ok(self.persona.line("how_are_you")), 25, examples=("how are you",))
        add("who", [r"who are you", r"what are you", r"what(?:'s| is) your name", r"introduce yourself"],
            lambda m: ok(self.persona.line("who", name=self.name)), 25, examples=("who are you",))

        # voice + settings
        add("voice_status", [r"voice(?: status| settings| info)?", r"(?:is|are) (?:voice|you listening)(?: on)?"],
            self.h_voice_status, 30, examples=("voice status",), help="voice status")
        add("voice_output",
            [r"(?:turn |switch )?(?:voice output|voice replies|speech(?: output)?|talking|tts|spoken replies)\s+(on|off)",
             r"(?:turn|switch) (on|off) (?:the )?(?:voice output|speech|tts|talking)",
             r"(enable|disable) (?:voice output|speech|tts|talking)"],
            lambda m: self.h_voice(m.group(1), which="output"), 30,
            examples=("voice output on", "voice output off"), help="voice output on|off · mute · unmute")
        add("voice_input",
            [r"(?:turn |switch )?(?:voice input|voice commands|listening|microphone|mic)\s+(on|off)",
             r"(start|stop) listening", r"(enable|disable) (?:voice input|voice commands|the mic(?:rophone)?|listening)",
             r"(?:turn|switch) (on|off) (?:the )?(?:mic(?:rophone)?|voice input)"],
            lambda m: self.h_voice(m.group(1), which="input"), 30,
            examples=("voice input on", "start listening", "stop listening"), help="voice input on|off · start/stop listening")
        add("voice_both", [r"(?:turn |switch )?voice(?: mode)?\s+(on|off)", r"(enable|disable) voice(?: mode)?"],
            lambda m: self.h_voice(m.group(1), which="both"), 30, examples=("voice on", "voice off"),
            help="voice on|off — both directions")
        add("mute", [r"(?:mute|be quiet|quiet|shut up|stop talking|silence|stay quiet)(?: yourself| please)?"],
            lambda m: self.h_voice("off", which="output"), 30, examples=("mute",))
        add("unmute", [r"(?:unmute|speak up|talk to me|you can (?:talk|speak)(?: now)?)"],
            lambda m: self.h_voice("on", which="output"), 30, examples=("unmute",))
        add("remarks", [r"(?:turn |switch )?(?:remarks|personality|banter|sarcasm|jokes)\s+(on|off)"],
            self.h_remarks, 30, examples=("remarks off",), help="remarks on|off — personality level")
        add("monitoring", [r"(?:turn |switch )?(?:background )?monitoring\s+(on|off)", r"(start|stop) monitoring",
                           r"(enable|disable) (?:background )?monitoring"],
            self.h_monitoring, 30, examples=("monitoring on", "monitoring off"),
            help="monitoring on|off — battery/RAM/CPU/disk alerts")
        add("settings_show", [r"(?:show |list |view |current )?(?:my )?(?:settings|config|configuration|preferences)"],
            self.h_settings_show, 30, examples=("show settings",), help="settings · set <key> to <value> · save settings")
        add("settings_save", [r"(?:save|store|keep) (?:the |my )?(?:settings|config|configuration|preferences|changes)"],
            lambda m: self.settings.save(), 30, examples=("save settings",))

        # system — "check/show/get/tell me (the|my) ..." is accepted in front of all of these
        P = r"(?:(?:check|show|get|tell me|give me|display|what about)\s+(?:me\s+)?)?(?:(?:the|my)\s+)?"
        add("system_status", [P + r"(?:system|sys|computer|pc|machine|laptop)?\s*(?:status|info|information|summary|health|report|stats)",
                              P + r"how(?:'s| is) (?:the |my )?(?:system|computer|pc|machine|laptop)(?: doing)?",
                              P + r"(?:check|show) (?:the )?(?:system|computer)(?: status)?", P + r"check cpu and ram"],
            self.h_system_status, 35, examples=("system status",), help="system status · cpu · memory · disk · battery · uptime · temperature · top processes")
        add("cpu", [P + r"(?:cpu|processor)(?: usage| load| status| info| use)?",
                    P + r"how busy is (?:the |my )?(?:cpu|computer|system|pc)", P + r"what(?:'s| is) (?:the |my )?cpu(?: usage| load)?"],
            lambda m: self.system.cpu(), 35, examples=("cpu usage",))
        add("memory", [P + r"(?:ram|memory|mem)(?: usage| status| info| use)?", P + r"how much (?:ram|memory)(?: is)?(?: free| used| left| available)?(?: do i have)?(?: left)?",
                       P + r"what(?:'s| is) (?:my |the )?(?:ram|memory)(?: usage)?"],
            lambda m: self.system.memory(), 35, examples=("memory usage", "ram"))
        add("disk", [P + r"(?:disk|storage|drive|space)(?: usage| space| status| info| left)?(?: (?:on|for|of) (.+))?",
                     P + r"how much (?:disk |storage |free )?space(?: is left| do i have(?: left)?| is free)?(?: on (.+))?",
                     P + r"(?:check|show) (?:the )?disk(?: space)?(?: on (.+))?"],
            self.h_disk, 35, examples=("disk space",))
        add("battery", [P + r"(?:battery|charge|power)(?: level| status| percentage| life| left)?",
                        P + r"how much (?:battery|charge)(?: do i have| is left)?(?: left)?",
                        P + r"am i (?:plugged in|charging|on battery)", P + r"what(?:'s| is) (?:my |the )?battery(?: level| at)?"],
            lambda m: self.system.battery(), 35, examples=("battery",))
        add("uptime", [P + r"(?:system )?uptime", P + r"how long (?:has|have) (?:the (?:system|computer|machine)|i|you|it) been (?:up|on|running)"],
            lambda m: self.system.uptime(), 35, examples=("uptime",))
        add("temperature", [P + r"(?:cpu |system )?(?:temp|temps|temperature|temperatures)", P + r"how hot is (?:the |my )?(?:cpu|computer|system|pc|laptop)"],
            lambda m: self.system.temperatures(), 35, examples=("temperature",))
        add("top_processes", [P + r"(?:top|heavy|heaviest|biggest) (?:processes|apps|programs|memory users)",
                              P + r"what(?:'s| is) using (?:my |the |all the |so much )?(?:memory|ram)", P + r"process(?:es)?(?: list)?"],
            lambda m: self.system.top(5), 35, examples=("top processes",))

        # network
        add("wifi_toggle", [P + r"(?:turn |switch )?(?:wi-?fi|wireless|wlan)\s+(on|off)", P + r"(?:turn|switch) (on|off) (?:the )?(?:wi-?fi|wireless)",
                            P + r"(enable|disable) (?:the )?(?:wi-?fi|wireless)"],
            lambda m: self.net.set_wifi(m.group(1).lower() in ON_WORDS), 40,
            examples=("wifi on", "wifi off"), help="wifi status · wifi on|off · scan wifi · network status")
        add("wifi_scan", [P + r"(?:scan|list|show|search)(?: for)? (?:available |nearby )?(?:wi-?fi|wireless)(?: networks)?",
                          P + r"(?:available|nearby) (?:wi-?fi )?networks"],
            lambda m: self.net.scan(), 40, examples=("scan wifi",))
        add("wifi_status", [P + r"(?:wi-?fi|wireless|wlan)(?: status| info| signal)?", P + r"what (?:wi-?fi|network) am i (?:on|connected to)",
                            P + r"which (?:wi-?fi|network)(?: am i on)?"],
            lambda m: self.net.wifi(), 40, examples=("wifi status",))
        add("network", [P + r"(?:network|internet|connection|net|connectivity)(?: status| info| check)?", P + r"am i (?:online|connected)(?: to the internet)?",
                        P + r"(?:is|check) (?:the |my )?(?:internet|connection|network)(?: working| up| ok)?",
                        P + r"(?:what(?:'s| is) )?my (?:local )?ip(?: address)?", P + r"ip(?: address)?"],
            lambda m: self.net.status(), 40, examples=("network status", "am i online"))

        # desktop actions
        add("lock", [r"lock(?: the| my)?(?: screen| computer| pc| session| laptop| machine)?"],
            lambda m: self.platform.lock_screen(), 45, examples=("lock screen",), help="lock screen")
        add("reminder_list", [r"(?:list|show|what are)(?: my)?(?: the)? (?:reminders|timers)", r"(?:my )?(?:reminders|timers)"],
            self.h_reminder_list, 44, examples=("list reminders",))
        add("reminder_cancel", [r"(?:cancel|clear|delete|remove|stop)(?: all)?(?: my| the)? (?:reminders?|timers?)"],
            self.h_reminder_cancel, 44, examples=("cancel reminders",))
        add("remind", [rf"remind me\s+(?:in|after)\s+(?P<amount>\S+)\s*(?P<unit>{UNITS})\s+(?:to|that|about)?\s*(?P<what>.+)",
                       rf"remind me\s+(?:to|that|about)\s+(?P<what>.+?)\s+(?:in|after)\s+(?P<amount>\S+)\s*(?P<unit>{UNITS})",
                       rf"(?:set (?:a |an )?)?timer\s+(?:for\s+)?(?P<amount>\S+)\s*(?P<unit>{UNITS})",
                       r"(?:set (?:a |an )?)?(?P<amount>\S+?)[\s-]*(?P<unit>second|sec|minute|min|hour|hr)s?\s+timer"],
            self.h_remind, 44, examples=("remind me in 10 minutes to stretch", "set a timer for 5 minutes"),
            help="remind me in 10 minutes to <x> · timer 5 minutes · list/cancel reminders")
        add("notify", [r"(?:test|send a test) notification",
                       r"(?:notify me|notify|send (?:me )?(?:a )?notification|notification|alert me|pop ?up)"
                       r"(?:\s+(?:that|saying|about|with|to))?[\s:]+(.+)"],
            self.h_notify, 45, examples=("notify me build finished", "test notification"),
            help="notify me <message> · test notification")

        # opening things
        add("open", [r"(?:open|launch|start|run|fire up|bring up)\s+(?:up\s+)?(?P<target>.+)",
                     r"(?P<goto>go to|visit|browse to|navigate to)\s+(?P<target>.+)"],
            self.h_open, 50, examples=("open firefox", "open downloads", "open terminal", "open 1"),
            help="open <app | downloads | ~/path | file X | folder X | site.com> · open 2 (search result)")
        add("apps_list", [r"(?:list|show)(?: me)? (?:all )?(?:installed |my )?(?:apps|applications|programs)(?: matching (.+))?",
                          r"what apps (?:do i have|are installed)"],
            self.h_apps_list, 50, examples=("list apps",), help="list apps [matching x] · rescan apps")
        add("apps_rescan", [r"(?:rescan|refresh|reload|reindex|update) (?:the )?(?:apps|applications|app list|app index)"],
            self.h_apps_rescan, 50, examples=("rescan apps",))

        # files
        where = r"(?:\s+(?:in|under|inside|within)\s+(?:my |the )?(?P<where>.+))?"
        add("files", [rf"(?:find|locate|search for|look for|scan for)\s+(?:a |the |my |all |any )?(?P<kind>{KINDS})"
                      rf"\s+(?:named |called |matching |with |containing |about |like |of )?(?P<query>.+?){where}",
                      rf"(?:search|look through|scan) (?:my |the )?(?:files|computer|disk|drive|home)\s+for\s+(?P<query>.+?){where}",
                      rf"(?:find|locate|scan for|look for)\s+(?:my |the )?(?P<query>.+?){where}",
                      rf"where(?:'s| is| are| did i (?:put|save))\s+(?:my |the file |the folder )(?P<query>.+?){where}",
                      r"where(?:'s| is)\s+(?P<query>\S+\.\w{1,5})"],
            self.h_files, 60, examples=("find report.pdf", "find folder projects", "find pdfs about linux in downloads"),
            help="find <name> [in <folder>] · find folder <x> · find pdfs about <x> · open file <x>")

        # web
        add("weather_news", [r"(?:what(?:'s| is) the |show (?:me )?the |today'?s )?(weather|news|headlines)(?: today| like| forecast)?(?: (?:in|for|about) (.+))?"],
            lambda m: self.web.search(f"{m.group(1)} {m.group(2) or ''}".strip()), 64, examples=("weather",))
        add("web_site", [r"(?:search|look up|lookup|find|google)\s+(?:for\s+)?(.+?)\s+on\s+"
                         r"(youtube|wikipedia|github|google|bing|duckduckgo|reddit|stack ?overflow|startpage)",
                         r"(?:play|watch)\s+(.+?)\s+on\s+(youtube)"],
            lambda m: self.web.search(m.group(1), m.group(2)), 64, examples=("search linux kernel on wikipedia",))
        add("web_engine", [r"(?:search\s+)?(youtube|wikipedia|github|reddit|stack ?overflow|google|bing|duckduckgo|ddg)\s+(?:for\s+)?(.+)"],
            lambda m: self.web.search(m.group(2), m.group(1)), 65, examples=("youtube lofi music", "google kali tools"))
        add("web", [r"(?:search|look up|lookup|web search|search the web|search online|search the internet|browse)\s+(?:for\s+)?(?:about\s+)?(.+)"],
            lambda m: self.web.search(m.group(1)), 66, examples=("search for python tutorials",),
            help="search <query> · google <query> · youtube <query> · search <x> on wikipedia")
        add("question", [r"((?:what|who|where|when|why|how|which)(?:'s|'re)?\b.+\s.+)"],
            lambda m: self._question(m.group(1)), 90)

        # settings setter last so "set a timer ..." etc. are claimed first
        add("settings_set", [r"(?:set|change|update) (?:my |the )?(?P<key>.+?)\s+(?:to|=|as)\s+(?P<value>.+)",
                             r"call me (?P<name>.+)"],
            self.h_settings_set, 70, examples=("set remark chance to 0.2", "set search engine to google"))

    # -- handlers -------------------------------------------------------
    def _question(self, q: str) -> dict:
        r = self.web.search(q)
        if r["ok"]:
            r["text"] = "No offline brain yet — searching the web instead.\n" + r["text"]
        return r

    def h_unported(self, m) -> dict:
        feature = m.group(1).split(" on ")[0].strip().capitalize()
        return fail(self.persona.line("unported", feature=feature), error="unported")

    def h_exit(self, m) -> dict:
        self.running = False
        return ok(self.persona.line("farewell"))

    def h_stop(self, m) -> dict:
        self.voice.stop_speaking()
        self.pending = None
        return ok("", speech="")

    def h_help(self, m) -> dict:
        lines = [f"  {i.help}" for i in sorted(self.router.intents, key=lambda i: i.priority) if i.help]
        text = ("Commands (chain with 'and' / 'then' / ';'):\n" + "\n".join(lines)
                + "\n  Anything phrased as a question goes to a web search.")
        return ok(text, speech="Here's what I can do. It's on screen.")

    def h_time(self, m) -> dict:
        now = datetime.now()
        t = now.strftime("%I:%M %p").lstrip("0")
        extra = self.persona.remark("late_night") if now.hour >= 23 or now.hour < 4 else ""
        return ok(f"It's {t}." + (f" {extra}" if extra else ""))

    def h_date(self, m) -> dict:
        now = datetime.now()
        return ok(f"It's {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}.")

    def h_voice(self, word: str, which: str) -> dict:
        state = word.lower() in ON_WORDS
        results = []
        if which in ("output", "both"):
            r = self.voice.set_output(state)
            if r["ok"]:
                self.settings.set("voice.output_enabled", state)
            results.append(r)
        if which in ("input", "both"):
            r = self.voice.set_input(state)
            if r["ok"]:
                self.settings.set("voice.input_enabled", state)
            results.append(r)
        text = " ".join(r["text"] for r in results)
        if all(r["ok"] for r in results):
            return ok(text)
        return fail(text, error="; ".join(str(r["error"]) for r in results if not r["ok"]))

    def h_voice_status(self, m) -> dict:
        s = self.voice.status()
        return ok(f"Voice output: {'on' if s['output'] else 'off'} (engine: {s['tts'] or 'none found'}). "
                  f"Voice input: {'on' if s['input'] else 'off'} (recogniser: {s['stt']}).",
                  speech=f"Voice output is {'on' if s['output'] else 'off'}, input is {'on' if s['input'] else 'off'}.")

    def h_remarks(self, m) -> dict:
        on = m.group(1).lower() in ON_WORDS
        self.settings.set("personality.remark_chance", 0.35 if on else 0.0)
        return ok("Personality back on." if on else "Remarks off. Strictly business.")

    def h_monitoring(self, m) -> dict:
        word = next(g for g in m.groups() if g)
        on = word.lower() in ON_WORDS
        self.settings.set("monitor.enabled", on)
        return self.monitor.start() if on else self.monitor.stop()

    def h_settings_show(self, m) -> dict:
        g = self.settings.get
        v = self.voice.status()
        lines = [
            f"  config file      {self.settings.path}{'' if self.settings.path.exists() else ' (not created yet)'}",
            f"  user name        {g('user_name') or '(not set)'}   honorific: {g('personality.honorific') or '(none)'}",
            f"  remark chance    {g('personality.remark_chance')}",
            f"  voice output     {'on' if v['output'] else 'off'} (tts_backend={g('voice.tts_backend')}, rate={g('voice.tts_rate')})",
            f"  voice input      {'on' if v['input'] else 'off'} (stt_backend={g('voice.stt_backend')}, wake word='{g('voice.wake_word')}',"
            f" required={g('voice.require_wake_word')})",
            f"  search engine    {g('web.search_engine')}",
            f"  file roots       {', '.join(g('files.search_roots'))} (max {g('files.max_results')} results)",
            f"  monitoring       {'running' if self.monitor.running else 'off'} (battery<{g('monitor.battery_low')}%, "
            f"ram>{g('monitor.ram_high')}%, every {g('monitor.interval_s')}s)",
            f"  notifications    {'on' if g('notifications.enabled') else 'off'}",
            "  settable keys    " + ", ".join(_friendly_keys()),
        ]
        return ok("Settings:\n" + "\n".join(lines), speech="Settings are on screen.")

    def h_settings_set(self, m) -> dict:
        g = m.groupdict()
        if g.get("name"):
            key, value = "user_name", g["name"]
        else:
            key = self.settings.find_settable(g["key"])
            value = g["value"]
            if key is None:
                return fail(f"'{g['key']}' isn't a setting I can change. Try one of: "
                            + ", ".join(_friendly_keys()) + ".", error="unknown setting")
        if key == "web.search_engine" and not self.web.canonical(value):
            return fail(f"Unknown search engine '{value}'. Options: {', '.join(self.web.engines())}.", error="bad value")
        try:
            new = self.settings.set(key, value)
        except (ValueError, KeyError) as e:
            return fail(f"Couldn't set {key}: {e}", error=str(e))
        if key == "web.search_engine":
            new = self.settings.set(key, self.web.canonical(value))
        return ok(f"{key} = {new!r}. Say 'save settings' to keep it.", speech=f"Done. {key.split('.')[-1].replace('_', ' ')} set.")

    def h_system_status(self, m) -> dict:
        r = self.system.summary()
        cpu = self.system.snapshot().get("cpu") if r["ok"] else None
        if cpu is not None and cpu > 85:
            quip = self.persona.remark("busy")
            if quip:
                r["text"] += f"\n  {quip}"
        return r

    def h_disk(self, m) -> dict:
        target = next((g for g in m.groups() if g), None)
        if target:
            p = self.files.resolve_root(target)
            if not p:
                return fail(f"I don't know a folder called '{target}'.", error="bad path")
            return self.system.disk([str(p)])
        return self.system.disk()

    def h_remind(self, m) -> dict:
        g = m.groupdict()
        amount, unit = g["amount"], g["unit"]
        what = (g.get("what") or "").strip() or "Timer finished."
        seconds = parse_duration(amount, unit)
        if not seconds or seconds <= 0:
            return fail(f"I couldn't understand '{amount} {unit}'.", error="bad duration")
        if seconds > 7 * 86400:
            return fail("Keep it under a week — reminders only live while I'm running.", error="too long")
        what = what.strip()
        rem = {"text": what, "due": time.time() + seconds}

        def fire():
            self.reminders[:] = [r for r in self.reminders if r is not rem]
            msg = f"Reminder: {what}" if what != "Timer finished." else what
            self.output(f"[reminder] {msg}")
            self.notify(self.name, msg, "normal")
            self.voice.say(msg)

        rem["timer"] = threading.Timer(seconds, fire)
        rem["timer"].daemon = True
        rem["timer"].start()
        self.reminders.append(rem)
        when = datetime.fromtimestamp(rem["due"]).strftime("%I:%M %p").lstrip("0")
        return ok(f"Okay — in {fmt_duration(seconds) if seconds >= 60 else f'{int(seconds)} seconds'} ({when}): {what}",
                  speech=f"Reminder set for {when}.")

    def h_reminder_list(self, m) -> dict:
        if not self.reminders:
            return ok("No reminders pending.")
        lines = [f"  {datetime.fromtimestamp(r['due']).strftime('%I:%M %p').lstrip('0')}  {r['text']}"
                 for r in sorted(self.reminders, key=lambda r: r["due"])]
        return ok("Pending reminders:\n" + "\n".join(lines), speech=f"You have {len(lines)} pending.")

    def h_reminder_cancel(self, m) -> dict:
        n = len(self.reminders)
        for r in self.reminders:
            r["timer"].cancel()
        self.reminders.clear()
        return ok(f"Cancelled {n} reminder{'s' * (n != 1)}.")

    def h_notify(self, m) -> dict:
        body = m.group(1) if m.lastindex else "Test notification — notifications are working."
        r = self.notify(self.name, body.strip())
        if r["ok"]:
            r["text"] = f"Notification sent: {body.strip()}"
            r["speech"] = "Sent."
        return r

    def h_open(self, m) -> dict:
        target = m.group("target").strip().strip("'\"")
        goto = bool(m.groupdict().get("goto"))
        low = target.lower()
        # 1) a numbered result from the last file search
        if self.last_results and re.fullmatch(
                r"(?:the |result |file |number |#)*(?:\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|"
                r"ninth|tenth|last)(?: one| result| file)?", low):
            idx = parse_choice(low, len(self.last_results))
            if idx is None:
                return fail(f"There are only {len(self.last_results)} results.", error="bad index")
            return self.platform.open_path(self.last_results[idx])
        # 2) well-known folders
        folder = re.fullmatch(r"(?:my |the )?(downloads?|documents?|desktop|music|pictures?|photos|videos?|"
                              r"templates|public|home)(?: folder| directory)?", low)
        if folder:
            p = self.platform.user_dir(folder.group(1))
            return self.platform.open_path(str(p)) if p else fail(f"I can't find your {folder.group(1)} folder.",
                                                                  error="missing")
        # 3) explicit path
        if re.match(r"^(?:~|/|\./|\.\./)", target):
            return self.platform.open_path(target)
        # 4) URLs and a few named sites
        if URL_RE.fullmatch(target):
            url = target if re.match(r"https?://", target, re.I) else f"https://{target}"
            r = self.platform.open_url(url)
            return ok(f"Opening {url}", speech="Opening it.") if r["ok"] else r
        site = re.fullmatch(r"(youtube|github|gmail|reddit|wikipedia|stack ?overflow|chatgpt|claude|google)"
                            r"(?:\.com)?(?: website| site)?", low)
        if site and goto:
            return self.platform.open_url(SITES.get(site.group(1), SITES.get(site.group(1).replace(" ", ""))))
        # 5) "open file X" / "open folder X" -> search, open if unambiguous
        fm = re.fullmatch(r"(?:the )?(file|document|folder|directory)\s+(?:named |called )?(.+)", target, re.I)
        if fm:
            return self._open_file_query(fm.group(2), "dir" if fm.group(1).lower() in ("folder", "directory") else "file")
        # 6) an app (sites like "youtube" after "open" fall back to the browser if no app matches)
        r = self.apps.launch(target)
        if r["ok"]:
            r["text"] = self.persona.line("open", name=r.get("data", {}).get("app", target))
            return r
        if r.get("error") == "ambiguous":
            self._set_pending("app_choice", r["data"]["choices"])
            return r
        if r.get("error") == "not_found":
            if site:
                return self.platform.open_url(SITES.get(site.group(1), SITES.get(site.group(1).replace(" ", ""))))
            if re.search(r"\.\w{1,5}$", target):           # looks like a filename, not an app
                return self._open_file_query(target, "file")
            if goto:
                return self.web.search(target)
            r["text"] = self.persona.line("app_not_found", name=target)
        return r

    def _open_file_query(self, query: str, kind: str) -> dict:
        """Search, open the hit if it's unambiguous, otherwise list the matches."""
        r = self.files.search(query, kind=kind)
        results = r.get("data", {}).get("results") or []
        exact = results and os.path.basename(results[0]).lower() in (
            query.lower(), os.path.splitext(os.path.basename(results[0]))[0].lower())
        if len(results) == 1 or exact:
            return self.platform.open_path(results[0])
        self.last_results = results
        return r

    def h_apps_list(self, m) -> dict:
        index = self.apps.index()
        if not index:
            return fail("I couldn't find any installed desktop apps.", error="empty index")
        flt = (m.group(1) or "").lower() if m.lastindex else ""
        names = sorted({e.name for e in index if flt in e.name.lower()}, key=str.lower)
        if not names:
            return fail(f"No apps matching '{flt}'.", error="not_found")
        shown = names[:60]
        more = f"\n  …and {len(names) - 60} more (try 'list apps matching <x>')" if len(names) > 60 else ""
        return ok(f"{len(names)} apps:\n  " + ", ".join(shown) + more, speech=f"I found {len(names)} apps.")

    def h_apps_rescan(self, m) -> dict:
        n = len(self.apps.index(refresh=True))
        return ok(f"App index rebuilt: {n} apps.")

    def h_files(self, m) -> dict:
        g = m.groupdict()
        query, where, kind, exts = g["query"].strip(), g.get("where"), "any", ()
        word = (g.get("kind") or "").lower().rstrip("s")
        if word.startswith("folder") or word.startswith("director"):
            kind = "dir"
        elif word in ("file", "document"):
            kind = "file"
        elif word:
            kind, exts = "file", EXT_FILTERS.get(word, ())
        root = None
        if where:
            root = self.files.resolve_root(where)
            if root is None:                       # "notes in linux" — treat as part of the name
                query = f"{query} in {where}"
        query = re.sub(r"^(?:named|called)\s+", "", query, flags=re.I)
        r = self.files.search(query, kind=kind, root=root, exts=exts)
        if not r["ok"] and r.get("error") == "not_found":
            quip = self.persona.remark("not_found")
            if quip:
                r["text"] += f" {quip}"
        self.last_results = r.get("data", {}).get("results") or []
        return r


# ── CLI ──────────────────────────────────────────────────────────────────
def run_check(j: Jarvis, log_file) -> int:
    d = j.platform.diagnostics()
    v = j.voice.status()
    print(f"JARVIS {__version__} self-check")
    print(f"  python        {sys.version.split()[0]}  ({sys.executable})")
    print(f"  platform      {d.get('platform')}  desktop={d.get('desktop') or '-'}  session={d.get('session') or '-'}"
          f"  display={d.get('display')}  root={d.get('root')}")
    print(f"  config        {j.settings.path} ({'exists' if j.settings.path.exists() else 'defaults only'})")
    print(f"  log file      {log_file or 'console only'}")
    for w in j.settings.warnings:
        print(f"  WARNING       {w}")
    tools = d.get("tools", {})
    if tools:
        have = [t for t, v_ in tools.items() if v_]
        miss = [t for t, v_ in tools.items() if not v_]
        print(f"  tools found   {', '.join(have) or '-'}")
        print(f"  tools missing {', '.join(miss) or '-'}")
    print(f"  apps indexed  {len(j.apps.index())}")
    print(f"  tts engine    {v['tts'] or 'none (sudo apt install espeak-ng)'}")
    print(f"  stt           {v['stt']}")
    online = j.net.internet()[0]
    print(f"  internet      {'online' if online else 'offline'}")
    return 0


def repl(j: Jarvis) -> None:
    hist = state_home() / "history"
    try:
        import readline
        try:
            readline.read_history_file(hist)
        except OSError:
            pass
        readline.set_history_length(500)
    except ImportError:
        readline = None
    main_thread = threading.main_thread()

    def out(text: str) -> None:
        if threading.current_thread() is main_thread:
            print(f"{j.name}: {text}", flush=True)
        else:                              # voice / reminder / monitor output while input() waits
            print(f"\r{j.name}: {text}\nyou> ", end="", flush=True)

    j.output = out
    print(f"{j.name} {__version__} — type 'help' for commands, 'exit' to quit.")
    while j.running:
        try:
            line = input("you> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            if j.voice.is_speaking():
                j.voice.stop_speaking()
                continue
            break
        j.handle(line, source="text")
    if readline:
        try:
            hist.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(hist)
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis", description="JARVIS — lightweight Linux assistant")
    p.add_argument("-c", "--command", action="append", metavar="TEXT",
                   help="run a command and exit (repeatable)")
    p.add_argument("--config", metavar="PATH", help="config file (default: ./jarvis_config.json or ~/.config/jarvis/config.json)")
    p.add_argument("--voice", action=argparse.BooleanOptionalAction, default=None, help="voice input+output")
    p.add_argument("--voice-in", action=argparse.BooleanOptionalAction, default=None, help="voice input")
    p.add_argument("--voice-out", action=argparse.BooleanOptionalAction, default=None, help="voice output")
    p.add_argument("--daemon", action="store_true", help="no text prompt; run voice/monitor until Ctrl+C or SIGTERM")
    p.add_argument("--check", action="store_true", help="print a self-check of available features and exit")
    p.add_argument("--no-greet", action="store_true", help="skip the startup greeting")
    p.add_argument("--allow-root", action="store_true", help="run even as root (not recommended)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging to the console")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(PROJECT_DIR / ".env")
    load_dotenv(config_home() / ".env")
    settings = Settings.load(args.config)
    log_file = setup_logging(settings, verbose=args.verbose)
    for w in settings.warnings:
        log.warning(w)
    log.info("starting JARVIS %s (config=%s)", __version__, settings.path)

    if hasattr(os, "geteuid") and os.geteuid() == 0 and settings.get("safety.refuse_root") and not args.allow_root:
        print("JARVIS refuses to run as root. Start it as your normal user "
              "(or pass --allow-root if you really mean it).", file=sys.stderr)
        return 2

    j = Jarvis(settings)
    if args.check:
        return run_check(j, log_file)

    voice_in = args.voice_in if args.voice_in is not None else args.voice
    voice_out = args.voice_out if args.voice_out is not None else args.voice

    def _term(signum, frame):
        j.running = False
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)

    try:
        if args.command:
            j.start(voice_in=False, voice_out=bool(voice_out), greet=False, monitor=False)
            results = []
            for c in args.command:
                results += j.handle(c, source="cli")
            if j.voice.output_enabled:
                j.wait_for_speech()
            if j.reminders:
                print("(note: reminders only fire while Jarvis keeps running)", file=sys.stderr)
            return 0 if results and all(r.get("ok") for r in results) else 1

        j.start(voice_in=voice_in, voice_out=voice_out, greet=not args.no_greet)
        if args.daemon:
            while j.running:
                time.sleep(0.5)
        else:
            repl(j)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        j.shutdown()


if __name__ == "__main__":
    sys.exit(main())

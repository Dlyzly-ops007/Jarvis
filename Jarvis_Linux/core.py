"""Shared foundation: the result contract, settings and logging.

Every capability returns a plain dict:
    {"ok": bool, "text": str, "error": str | None, "speech"?: str, "data"?: dict}
`text` is what the terminal shows, `speech` (optional) is a shorter spoken form.
Nothing in the capability layer should raise into the router.

Settings are layered, lowest to highest priority:
    DEFAULTS  <-  config file (JSON)  <-  environment (JARVIS_*)  <-  runtime `set` commands
Only the file layer + runtime changes are written back by `save()`, so secrets
or overrides passed through the environment are never persisted.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
log = logging.getLogger("jarvis.core")


# ── result contract ───────────────────────────────────────────────────────
def ok(text: str = "", speech: str | None = None, **data) -> dict:
    result = {"ok": True, "text": text, "error": None}
    if speech is not None:
        result["speech"] = speech
    if data:
        result["data"] = data
    return result


def fail(text: str, error: str | None = None, speech: str | None = None, **data) -> dict:
    result = {"ok": False, "text": text, "error": error or text}
    if speech is not None:
        result["speech"] = speech
    if data:
        result["data"] = data
    return result


# ── paths (XDG) ───────────────────────────────────────────────────────────
def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "jarvis"


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or "~/.local/state").expanduser() / "jarvis"


# ── defaults ──────────────────────────────────────────────────────────────
DEFAULTS: dict = {
    "assistant_name": "Jarvis",
    "user_name": "",
    "personality": {
        "honorific": "sir",          # "" to disable
        "remark_chance": 0.35,       # 0 = no optional remarks, 1 = always
        "greet_on_start": True,
    },
    "voice": {
        "input_enabled": False,
        "output_enabled": False,
        "tts_backend": "auto",       # auto | piper | espeak-ng | espeak | spd-say | pyttsx3
        "tts_rate": 170,             # words per minute (espeak scale)
        "tts_voice": "en",
        "piper_binary": "piper",
        "piper_model": "",           # path to a .onnx voice; empty = don't use piper
        "stt_backend": "google",     # google (online) | vosk (offline) | whisper (offline)
        "language": "en-US",
        "vosk_model_path": "",
        "whisper_model": "base.en",
        "wake_word": "jarvis",
        "require_wake_word": True,
        "mic_device_index": -1,      # -1 = system default
        "phrase_time_limit": 8,
    },
    "apps": {
        "aliases": {},               # {"code": "visual studio code"}
        "blocked": ["root terminal", "gparted", "synaptic"],
        "allow_path_fallback": False,
    },
    "files": {
        "search_roots": ["~"],
        "exclude_dirs": ["node_modules", "__pycache__", ".git", ".cache", "venv",
                         ".venv", "site-packages", "snap", "Trash"],
        "include_hidden": False,
        "max_results": 10,
        "max_depth": 10,
        "time_budget_s": 4.0,
        "use_locate": True,
    },
    "web": {
        "search_engine": "duckduckgo",
        "engines": {},               # extra/override: {"name": "https://...{q}"}
    },
    "network": {
        "check_hosts": ["1.1.1.1:53", "8.8.8.8:53"],
        "timeout_s": 2.0,
        "allow_wifi_toggle": True,
    },
    "monitor": {
        "enabled": True,
        "interval_s": 60,
        "battery_low": 20,
        "battery_critical": 10,
        "battery_high": 0,           # e.g. 80 to get an "unplug" nudge; 0 = off
        "ram_high": 90,
        "cpu_high": 95,
        "cpu_sustain_checks": 3,
        "disk_low_free_pct": 10,
        "disk_paths": ["/", "~"],
    },
    "notifications": {
        "enabled": True,
        "app_name": "Jarvis",
        "timeout_ms": 6000,
    },
    "logging": {
        "level": "INFO",
        "console_level": "WARNING",
        "dir": "",                   # empty = ~/.local/state/jarvis
        "max_bytes": 1_000_000,
        "backups": 3,
    },
    "safety": {
        "refuse_root": True,
    },
}

# Keys the "set <x> to <y>" command may change at runtime.
SETTABLE = (
    "user_name",
    "personality.honorific",
    "personality.remark_chance",
    "personality.greet_on_start",
    "voice.tts_backend",
    "voice.tts_rate",
    "voice.tts_voice",
    "voice.stt_backend",
    "voice.language",
    "voice.wake_word",
    "voice.require_wake_word",
    "voice.phrase_time_limit",
    "files.max_results",
    "files.include_hidden",
    "web.search_engine",
    "monitor.battery_low",
    "monitor.battery_high",
    "monitor.ram_high",
    "monitor.interval_s",
    "notifications.enabled",
)

_TRUE = {"1", "true", "yes", "on", "y", "enabled"}
_FALSE = {"0", "false", "no", "off", "n", "disabled"}


def coerce(value, like):
    """Convert `value` (usually a str) to the type of `like`. Raises ValueError."""
    if not isinstance(value, str):
        if isinstance(like, bool) and isinstance(value, bool):
            return value
        if isinstance(like, (int, float)) and not isinstance(like, bool) and isinstance(value, (int, float)):
            return type(like)(value)
        if isinstance(like, (list, dict)) and isinstance(value, type(like)):
            return value
        if isinstance(like, str):
            return str(value)
        raise ValueError(f"expected {type(like).__name__}, got {type(value).__name__}")
    v = value.strip()
    if isinstance(like, bool):
        if v.lower() in _TRUE:
            return True
        if v.lower() in _FALSE:
            return False
        raise ValueError(f"'{value}' is not a yes/no value")
    if isinstance(like, int):
        return int(float(v))
    if isinstance(like, float):
        return float(v)
    if isinstance(like, list):
        if v.startswith("["):
            return list(json.loads(v))
        return [p.strip() for p in v.split(",") if p.strip()]
    if isinstance(like, dict):
        return dict(json.loads(v))
    return v


def _deep_merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _dig(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def _put(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def load_dotenv(path: Path, env: dict | None = None) -> int:
    """Minimal .env reader (KEY=VALUE, # comments). Existing variables win."""
    env = os.environ if env is None else env
    count = 0
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in env:
            env[key] = val
            count += 1
    return count


class Settings:
    def __init__(self, data: dict | None = None, path: Path | None = None,
                 file_data: dict | None = None):
        self.data = _deep_merge(copy.deepcopy(DEFAULTS), copy.deepcopy(data or {}))
        self.path = Path(path) if path else config_home() / "config.json"
        self.file_data = copy.deepcopy(file_data or {})
        self.warnings: list[str] = []

    # -- loading --------------------------------------------------------
    @staticmethod
    def find_config(explicit: str | None = None, env: dict | None = None) -> Path:
        env = os.environ if env is None else env
        for cand in (explicit, env.get("JARVIS_CONFIG")):
            if cand:
                return Path(cand).expanduser()
        local = PROJECT_DIR / "jarvis_config.json"
        if local.exists():
            return local
        return config_home() / "config.json"

    @classmethod
    def load(cls, path: str | Path | None = None, env: dict | None = None) -> "Settings":
        env = os.environ if env is None else env
        cfg_path = Path(path).expanduser() if path else cls.find_config(None, env)
        file_data: dict = {}
        warnings = []
        if cfg_path.exists():
            try:
                file_data = json.loads(cfg_path.read_text(encoding="utf-8")) or {}
                if not isinstance(file_data, dict):
                    raise ValueError("top level must be an object")
            except (OSError, ValueError) as e:
                warnings.append(f"Ignoring unreadable config {cfg_path}: {e}")
                file_data = {}
        s = cls(file_data, cfg_path, file_data)
        s.warnings.extend(warnings)
        s._apply_env(env)
        return s

    def _apply_env(self, env) -> None:
        for key, raw in env.items():
            if not key.startswith("JARVIS_") or key in ("JARVIS_CONFIG",):
                continue
            dotted = key[len("JARVIS_"):].lower().replace("__", ".")
            try:
                like = _dig(DEFAULTS, dotted)
            except KeyError:
                continue
            try:
                _put(self.data, dotted, coerce(raw, like))
            except (ValueError, json.JSONDecodeError) as e:
                self.warnings.append(f"Ignoring {key}: {e}")

    # -- access ---------------------------------------------------------
    def get(self, dotted: str, default=None):
        try:
            return _dig(self.data, dotted)
        except KeyError:
            return default

    def set(self, dotted: str, value, persist: bool = True):
        """Set a known key, coercing to the default's type. Returns the new value."""
        like = _dig(DEFAULTS, dotted)            # KeyError for unknown keys
        new = coerce(value, like)
        _put(self.data, dotted, new)
        if persist:
            _put(self.file_data, dotted, new)
        return new

    def find_settable(self, friendly: str) -> str | None:
        """'speech rate' -> 'voice.tts_rate'-style lookup over SETTABLE."""
        key = friendly.strip().lower().replace("-", "_").replace(" ", "_")
        synonyms = {"speech_rate": "tts_rate", "voice_speed": "tts_rate", "rate": "tts_rate",
                    "voice": "tts_voice", "engine": "search_engine", "name": "user_name",
                    "my_name": "user_name", "remarks": "remark_chance", "title": "honorific",
                    "tts": "tts_backend", "stt": "stt_backend",
                    "notifications": "notifications.enabled"}
        key = synonyms.get(key, key)
        if key in SETTABLE:
            return key
        if f"{key}.enabled" in SETTABLE:
            key = f"{key}.enabled"
        if key in SETTABLE:
            return key
        hits = [k for k in SETTABLE if k.split(".")[-1] == key]
        return hits[0] if len(hits) == 1 else None

    def save(self) -> dict:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.file_data, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.path)
            return ok(f"Settings saved to {self.path}.", speech="Settings saved.")
        except OSError as e:
            return fail(f"Couldn't save settings to {self.path}.", error=str(e))


# ── logging ───────────────────────────────────────────────────────────────
def setup_logging(settings: Settings, verbose: bool = False) -> Path | None:
    root = logging.getLogger("jarvis")
    root.setLevel(logging.DEBUG)
    root.propagate = False
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else
                     getattr(logging, str(settings.get("logging.console_level")).upper(), logging.WARNING))
    console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)

    log_dir = Path(settings.get("logging.dir") or state_home()).expanduser()
    log_file = log_dir / "jarvis.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=int(settings.get("logging.max_bytes")),
                                 backupCount=int(settings.get("logging.backups")), encoding="utf-8")
        fh.setLevel(getattr(logging, str(settings.get("logging.level")).upper(), logging.INFO))
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        root.warning("File logging disabled (%s): %s", log_file, e)
        return None
    return log_file

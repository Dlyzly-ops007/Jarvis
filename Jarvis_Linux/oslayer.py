"""OS abstraction. Everything OS-specific goes through a Platform object.

`PlatformBase` defines the interface; every method has a safe default that
reports "not supported" instead of raising. `platform_linux.LinuxPlatform`
implements it for Linux. A future `platform_windows.py` only has to subclass
PlatformBase and be added to `get_platform()` — nothing else changes.

Convention:
  * data getters (cpu_stats, memory_stats, battery, ...) return a dict/list or None
  * actions (open_path, launch_app, notify, set_wifi, lock_screen) return a
    core result dict and never raise
"""
from __future__ import annotations

import re
import shutil
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

from core import fail, ok


# Anything that escalates privileges is never launched, on any platform.
PRIV_BINARIES = {"sudo", "pkexec", "su", "gksu", "gksudo", "kdesu", "kdesudo", "doas", "run0", "beesu"}
PRIV_RE = re.compile(r"(?:^|[\s;&|'\"(/])(" + "|".join(sorted(PRIV_BINARIES)) + r")(?=[\s;'\")]|$)")


def is_privileged_exec(exec_str: str) -> bool:
    return bool(PRIV_RE.search(exec_str or ""))


@dataclass
class AppEntry:
    name: str
    exec: str = ""
    desktop_id: str = ""
    path: str = ""
    terminal: bool = False
    generic_name: str = ""
    keywords: tuple = field(default_factory=tuple)
    categories: tuple = field(default_factory=tuple)
    source: str = "desktop"


class PlatformBase:
    name = "unsupported"

    def _unsupported(self, feature: str) -> dict:
        return fail(f"{feature} isn't supported on {self.name} yet.", error="unsupported")

    # -- generic helpers --------------------------------------------------
    def which(self, binary: str) -> str | None:
        return shutil.which(binary)

    def has_display(self) -> bool:
        return True

    def diagnostics(self) -> dict:
        return {"platform": self.name}

    # -- opening things ----------------------------------------------------
    def open_path(self, path: str) -> dict:
        return self._unsupported("Opening files")

    def open_url(self, url: str) -> dict:
        try:
            if webbrowser.open(url):
                return ok(f"Opened {url}")
        except webbrowser.Error as e:
            return fail("Couldn't open a browser.", error=str(e))
        return fail("Couldn't open a browser.", error="webbrowser.open returned False")

    def user_dir(self, name: str) -> Path | None:
        home = Path.home()
        cand = home / name.capitalize()
        return cand if cand.is_dir() else (home if name == "home" else None)

    # -- applications ------------------------------------------------------
    def list_apps(self) -> list[AppEntry]:
        return []

    def default_app(self, category: str, index: list[AppEntry]) -> AppEntry | None:
        return None

    def launch_app(self, entry: AppEntry) -> dict:
        return self._unsupported("Launching apps")

    def locate(self, pattern: str, limit: int = 2000) -> list[str] | None:
        """Fast indexed filename lookup; None = not available (caller walks)."""
        return None

    # -- notifications / session -------------------------------------------
    def notify(self, title: str, body: str, urgency: str = "normal",
               app_name: str = "Jarvis", timeout_ms: int = 6000) -> dict:
        return self._unsupported("Desktop notifications")

    def lock_screen(self) -> dict:
        return self._unsupported("Locking the screen")

    # -- system data -------------------------------------------------------
    def cpu_stats(self) -> dict | None:
        return None

    def memory_stats(self) -> dict | None:
        return None

    def battery(self) -> dict | None:
        return None

    def uptime_seconds(self) -> float | None:
        return None

    def temperatures(self) -> list[tuple[str, float]] | None:
        return None

    def top_processes(self, n: int = 5) -> list[dict] | None:
        return None

    # -- network -----------------------------------------------------------
    def network_interfaces(self) -> list[dict] | None:
        return None

    def default_gateway(self) -> str | None:
        return None

    def wifi_status(self) -> dict | None:
        return None

    def wifi_scan(self) -> dict:
        return self._unsupported("Wi-Fi scanning")

    def set_wifi(self, enabled: bool) -> dict:
        return self._unsupported("Wi-Fi control")


def get_platform() -> PlatformBase:
    if sys.platform.startswith("linux"):
        from platform_linux import LinuxPlatform
        return LinuxPlatform()
    # Windows / macOS implementations can be added here later.
    base = PlatformBase()
    base.name = sys.platform
    return base

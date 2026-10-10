"""Windows application launching primitives for JARVIS.

This module deliberately knows nothing about voice commands or natural-language
routing.  ``jarvis_main`` identifies the requested application and passes only
that application name here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import platform
import subprocess
import time
from typing import Callable, Mapping


@dataclass(frozen=True)
class ApplicationTarget:
    """A directly launchable Windows target."""

    display_name: str
    target: str
    kind: str = "executable"  # ``executable`` or ``shell`` (URI/file association)


@dataclass(frozen=True)
class LaunchResult:
    success: bool
    application: str
    method: str
    message: str
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# Add machine-specific entries here, or pass a replacement mapping to
# ``launch_application``. Executable names intentionally avoid user-specific
# absolute paths; when Windows cannot resolve one, Start-menu search takes over.
KNOWN_APPLICATIONS: dict[str, ApplicationTarget] = {
    "calculator": ApplicationTarget("Calculator", "calc.exe"),
    "chrome": ApplicationTarget("Google Chrome", "chrome.exe"),
    "command prompt": ApplicationTarget("Command Prompt", "cmd.exe"),
    "edge": ApplicationTarget("Microsoft Edge", "msedge.exe"),
    "file explorer": ApplicationTarget("File Explorer", "explorer.exe"),
    "notepad": ApplicationTarget("Notepad", "notepad.exe"),
    "paint": ApplicationTarget("Paint", "mspaint.exe"),
    "powershell": ApplicationTarget("PowerShell", "powershell.exe"),
    "settings": ApplicationTarget("Settings", "ms-settings:", kind="shell"),
    "spotify": ApplicationTarget("Spotify", "spotify:", kind="shell"),
    "terminal": ApplicationTarget("Windows Terminal", "wt.exe"),
    "visual studio code": ApplicationTarget("Visual Studio Code", "code.cmd"),
}

APPLICATION_ALIASES = {
    "calc": "calculator",
    "cmd": "command prompt",
    "explorer": "file explorer",
    "google chrome": "chrome",
    "microsoft edge": "edge",
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "windows settings": "settings",
    "windows terminal": "terminal",
}


def _normalise_name(application_name: str) -> str:
    return " ".join((application_name or "").strip().split()).casefold()


def resolve_application(
    application_name: str,
    known_applications: Mapping[str, ApplicationTarget] | None = None,
) -> ApplicationTarget:
    """Resolve a name to a configured target or a best-effort executable name."""

    name = _normalise_name(application_name)
    applications = known_applications or KNOWN_APPLICATIONS
    canonical = APPLICATION_ALIASES.get(name, name)
    if canonical in applications:
        return applications[canonical]

    # Windows may still resolve an unconfigured executable through PATH or a
    # file association. If it cannot, the Start-menu fallback will use the same
    # human-readable name.
    return ApplicationTarget(application_name.strip(), application_name.strip())


def _launch_direct(target: ApplicationTarget) -> tuple[bool, str | None]:
    if platform.system() != "Windows":
        return False, "direct application launching is only supported on Windows"

    try:
        if target.kind == "shell":
            os.startfile(os.path.expandvars(target.target))  # type: ignore[attr-defined]
        elif target.kind == "executable":
            subprocess.Popen(
                [os.path.expandvars(target.target)],
                close_fds=True,
            )
        else:
            return False, f"unsupported launch target kind: {target.kind}"
        return True, None
    except (OSError, ValueError) as exc:
        return False, str(exc)


def _start_menu_fallback(application_name: str) -> tuple[bool, str | None]:
    """Open Start, type the name, and press Enter without importing GUI code early."""

    if platform.system() != "Windows":
        return False, "Start-menu fallback is only supported on Windows"

    try:
        import pyautogui

        pyautogui.press("win")
        time.sleep(0.35)
        pyautogui.write(application_name, interval=0.025)
        time.sleep(0.15)
        pyautogui.press("enter")
        return True, None
    except Exception as exc:  # GUI automation can fail for several OS-level reasons.
        return False, str(exc)


def launch_application(
    application_name: str,
    *,
    known_applications: Mapping[str, ApplicationTarget] | None = None,
    direct_launcher: Callable[[ApplicationTarget], tuple[bool, str | None]] | None = None,
    fallback_launcher: Callable[[str], tuple[bool, str | None]] | None = None,
) -> LaunchResult:
    """Launch an application, falling back to Windows Start-menu search.

    Injectable launch functions keep the decision logic testable without
    opening programs during tests.
    """

    requested = (application_name or "").strip()
    if not requested:
        return LaunchResult(False, requested, "none", "No application name was provided.")

    target = resolve_application(requested, known_applications)
    direct = direct_launcher or _launch_direct
    fallback = fallback_launcher or _start_menu_fallback

    direct_ok, direct_error = direct(target)
    if direct_ok:
        return LaunchResult(
            True,
            target.display_name,
            "direct",
            f"Opened {target.display_name}.",
        )

    fallback_ok, fallback_error = fallback(target.display_name or requested)
    if fallback_ok:
        return LaunchResult(
            True,
            target.display_name or requested,
            "start_menu",
            f"Searched the Start menu for {target.display_name or requested}.",
            error=direct_error,
        )

    errors = "; ".join(error for error in (direct_error, fallback_error) if error)
    return LaunchResult(
        False,
        target.display_name or requested,
        "failed",
        f"Could not open {target.display_name or requested}.",
        error=errors or None,
    )


# A concise facade for callers that prefer the old naming style.
open_app = launch_application


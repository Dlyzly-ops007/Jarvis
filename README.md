# JARVIS

A modular personal AI assistant built in Python.

This is a reboot of an earlier JARVIS that grew into a large monolithic codebase. The reboot focuses on cleaner architecture, clear separation between components, and making the project suitable for public development.

## Current features

**Command routing** (`jarvis_main.py`) — commands are matched against registered rules (exact, prefix, contains, regex, or custom matcher functions) and dispatched to a handler. Covers status/quick-info, app control, browser/search, window/system control, Wi-Fi/Bluetooth, media, work profiles, reminders, game mode, clipboard/document commands, and more. Some handlers are still scaffolds/TODOs — the routing infrastructure is built so those can be filled in independently. Unmatched commands fall through to a fallback handler.

**Voice interface** (`voice_main.py`) — speech-to-text, wake-word detection, and text-to-speech, sitting between the user and `jarvis_main.py`. Wake-word matching is approximate, so variations like "jarvi" or "jervis" are recognized. Two modes: idle (waiting for the wake word) and command mode (speak freely until you say "stop" or the timeout hits). Listening and speaking can be toggled independently. Handles missing/broken microphones without crashing.

**System tray** (`GUI_Tray.py`) — JARVIS runs from the Windows system tray: a type-command window (with local history, up to 300 entries, duplicates ignored), listening/speaking controls, a system-monitor dashboard, and exit handling.

**System monitor** (`system_monitor.py`) — tracks CPU, RAM, GPU, and battery (charge, charging state, plugged state, time remaining, wear) on a 180-second interval, keeping the last 10 readings per metric. Includes a Tkinter dashboard with live cards and history. Uses `psutil` as the base, with NVIDIA NVML or `GPUtil` for GPU data and WMI for extra battery/temperature info where available.

**Wi-Fi / Bluetooth control** (`wireless.py`) — check/enable/disable/toggle both, via `netsh` and PowerShell. Windows-only, may need admin privileges.

**Notifications** (`notificationss.py`) — desktop notifications on startup/shutdown, falling back to a printed message if `winotify` isn't available.

## Requirements

Windows, Python 3.9+. See `requirements.txt` and `INSTRUCTIONS.md` for full setup, including the PyAudio install workaround for Windows.

```bash
pip install -r requirements.txt
python jarvis_main.py
```

## Roadmap

Real application launching and window control, browser automation, working clipboard/document tools, weather/news/conversion/translation, AI/LLM agent integration, persistent memory, reminders and automation, research tools, image/screen analysis, exam/quiz assistance, typing correction, structured logging, and interfaces beyond the tray.

## Status

Past the initial modular reboot into a working desktop-assistant foundation, with separate components for voice, command routing, system/feature modules, and the tray + monitoring + notifications layer. Main remaining work: replacing placeholder command handlers with real tools and wiring the fallback path to the planned AI/agent layer.

## License

See [LICENSE](LICENSE).
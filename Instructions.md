# JARVIS — Setup Instructions

This goes deeper than the README's quick-start — covers the full setup, optional-dependency quirks, and troubleshooting for each piece.

## 1. Prerequisites

- **Windows** — required. Several modules (`wireless.py`, parts of `system_monitor.py`, `notificationss.py`) call Windows-specific APIs (`netsh`, PowerShell, WMI) and won't work on macOS/Linux.
- **Python 3.9+**
- A working microphone, if you want voice input at all
- Administrator privileges — needed for some Wi-Fi/Bluetooth toggle operations, not for running JARVIS itself

## 2. Clone and install

```bash
git clone https://github.com/Dlyzly-ops007/Jarvis.git
cd Jarvis
pip install -r requirements.txt
```

## 3. PyAudio (microphone input)

`SpeechRecognition` needs `PyAudio` to actually read from a microphone, but `pip install pyaudio` on Windows often fails because it needs a compiled PortAudio backend that plain pip doesn't provide.

If `pip install pyaudio` fails, use a prebuilt wheel instead:
```bash
pip install pipwin
pipwin install pyaudio
```
or download a matching `.whl` for your Python version from [Christoph Gohlke's unofficial Windows binaries](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) and install it directly with `pip install <path-to-wheel>`.

## 4. Optional dependencies — what happens if they're missing

JARVIS is written to degrade gracefully rather than crash when an optional piece isn't available:

| Package | Used for | If missing |
|---|---|---|
| `pynvml` | NVIDIA GPU telemetry | Falls back to `GPUtil` |
| `GPUtil` | GPU usage/temp (non-NVIDIA path) | GPU stats just won't show |
| `WMI` | Extra Windows hardware/battery-health info | Monitor still works with `psutil`-only data |
| `winotify` | Desktop notifications | Falls back to printing the notification to console instead |

You don't need all of these installed for JARVIS to run — install what your setup supports and skip the rest.

## 5. Running JARVIS

```bash
python jarvis_main.py
```

This starts the system tray application (`GUI_Tray.py`), the voice listener, and the system monitor. Look for the JARVIS icon in your Windows system tray.

## 6. Using it

**Voice:** say the wake word ("Jarvis" — approximate matching also catches things like "jarvi" or "jervis"), wait for the greeting, then speak a command. You stay in command mode (no need to repeat the wake word) until you say "stop" or the command-mode timeout expires.

**Typed commands:** right-click the tray icon → "Type command..." — opens a window to type commands directly, no microphone needed. Successful commands are saved to local history (`command_history.json`, up to 300, duplicates ignored) and can be re-run from that list.

**Tray menu:**
- Type command...
- Controls... (enable/disable listening and speaking independently, or both)
- Monitor graphs... (opens the Tkinter system-monitor dashboard)
- Exit

## 7. System monitor data

Runs in the background regardless of whether you open the dashboard. Writes to `monitor_data.json` locally, sampling every 180 seconds, keeping the last 10 measurements per metric (CPU, RAM, GPU, battery). This file is generated at runtime — not something you need to create yourself.

## 8. Troubleshooting

- **Microphone not detected / speech recognition not working**: confirm `PyAudio` installed correctly (step 3), check Windows microphone permissions, and confirm you have internet access — the voice module uses Google's speech recognition API, which needs a network connection.
- **Wi-Fi/Bluetooth toggle commands not working**: these shell out to `netsh` and PowerShell — try running JARVIS as Administrator.
- **No GPU stats showing**: expected if you don't have an NVIDIA GPU and don't have `GPUtil` installed — this is a soft-fail, not a bug.
- **No desktop notifications**: `winotify` is likely missing or unsupported on your Windows version — JARVIS will print the notification text to the console instead of crashing.
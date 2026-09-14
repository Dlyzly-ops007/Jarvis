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
- Convo... (see section 9 — optional, only if AI Gateway is set up)
- Controls... (enable/disable listening and speaking independently, or both)
- Monitor graphs... (opens the Tkinter system-monitor dashboard)
- Exit

## 7. System monitor data

Runs in the background regardless of whether you open the dashboard. Writes to `monitor_data.json` locally, sampling every 180 seconds, keeping the last 10 measurements per metric (CPU, RAM, GPU, battery). This file is generated at runtime — not something you need to create yourself.

## 8. AI Gateway & Convo (optional)

Adds a persistent, multi-provider chat system — a ChatGPT/Claude-style **Convo** window in the tray, plus the same conversations reachable over Telegram. Fully separate from voice/typed commands; nothing here is required to run the rest of JARVIS, and skipping this section entirely is fine.

### 8.1 Install

Already covered by `pip install -r requirements.txt` (installs `litellm`). Two more are optional:

```bash
pip install python-dotenv      # auto-loads .env, see 8.3
pip install pyTelegramBotAPI   # only needed for the Telegram side, see 8.4
```

### 8.2 Get at least one provider API key

You only need **one** of these to use Convo — configuring more just gives you automatic fallback if one goes down or hits a rate limit.

| Provider | Get a key | Env var |
|---|---|---|
| OpenRouter | https://openrouter.ai/keys | `OPENROUTER_API_KEY` |
| Google Gemini | https://aistudio.google.com/apikey | `GEMINI_API_KEY` |
| Groq | https://console.groq.com/keys | `GROQ_API_KEY` |
| Ollama Cloud | https://ollama.com/settings/keys | `OLLAMA_API_KEY` |
| Local Ollama (Gemma 3) | https://ollama.com/download, then `ollama pull gemma3` | none — just needs to be running |
| FreeLLMAPI *(optional, self-hosted — not a signup page)* | https://github.com/S40014/freellmapi | `FREELLMAPI_API_BASE` (+ optional key) |

### 8.3 Configure

```bash
cp .env.example .env
```

Fill in whichever key(s) you got above. If `python-dotenv` isn't installed, export the same names as real environment variables instead — `.env` just won't be auto-loaded.

Default fallback order is `openrouter → gemini → groq → ollama_cloud → ollama_local`. Override it with:

```
AI_PROVIDER_ORDER=groq,gemini
```

Providers without a key set (or, for local Ollama, without anything reachable) are skipped automatically — you don't need to remove them from the order.

### 8.4 Telegram side (optional)

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, follow the prompts.
2. Put the token it gives you in `.env` as `TELEGRAM_BOT_TOKEN`.
3. `pip install pyTelegramBotAPI` if you haven't already.

That's it — the bot starts automatically in the background next time you run JARVIS, as long as a token is set. No token = it's simply not started, no error either way.

## 9. Using Convo

**Desktop:** right-click the tray icon → **Convo...**
- `+ New Chat` starts a fresh conversation
- Sidebar lists past chats, newest first — click one to switch; Rename/Delete above it
- Provider dropdown (top of the window) — leave on `auto` for the fallback chain, or pick one provider explicitly for that message
- Replies stream in as they arrive

**Telegram:** message your bot directly.
- `/newchat` — start a new conversation
- `/chats` — list and switch between existing ones (tap a button)
- `/rename <title>` — rename the current one
- `/delete` — delete the current one
- anything else you type is just sent as a message

Desktop and Telegram share the exact same conversations — start one on your phone, keep it going on desktop, or the other way around.

## 10. Convo storage

Each conversation is one JSON file under `ai_convo/chats/`, plus an `index.json` for the sidebar/search. Generated at runtime — nothing in there needs to be created or committed manually (already covered by the repo's `*.json` `.gitignore` rule). Safe to delete individual conversation files, or the whole `ai_convo/chats/` folder, to reset Convo history — JARVIS recreates whatever it needs on the next run.

## 11. Troubleshooting

- **Microphone not detected / speech recognition not working**: confirm `PyAudio` installed correctly (step 3), check Windows microphone permissions, and confirm you have internet access — the voice module uses Google's speech recognition API, which needs a network connection.
- **Wi-Fi/Bluetooth toggle commands not working**: these shell out to `netsh` and PowerShell — try running JARVIS as Administrator.
- **No GPU stats showing**: expected if you don't have an NVIDIA GPU and don't have `GPUtil` installed — this is a soft-fail, not a bug.
- **No desktop notifications**: `winotify` is likely missing or unsupported on your Windows version — JARVIS will print the notification text to the console instead of crashing.
- **Convo menu says "unavailable"**: `litellm` isn't installed — `pip install litellm` and restart JARVIS.
- **"AI error: no AI provider is configured"**: no API key is set for any provider — fill in at least one in `.env` (section 8.3) and restart.
- **Local Gemma 3 fallback never seems to trigger**: it only activates if something is actually listening on `http://localhost:11434` — install Ollama, make sure it's running, and `ollama pull gemma3` first.
- **Telegram bot doesn't respond**: confirm `pyTelegramBotAPI` is installed, `TELEGRAM_BOT_TOKEN` in `.env` is correct, and check the console for `telegram_convo_bot: polling started.` on startup.
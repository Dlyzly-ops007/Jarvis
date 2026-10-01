# JARVIS

A modular personal AI assistant built in Python, with separate implementations for Windows and Linux.

JARVIS is a reboot of an earlier monolithic codebase. The project now focuses on cleaner architecture, clear separation between components, platform-specific implementations, and public development.

## Downloads

| Version | Link |
| --- | --- |
| Windows | [View Windows build](./Jarvis_Windows) |
| Linux | [View Linux build](./Jarvis_Linux) |
| Complete repository | Use **Code > Download ZIP** on the repository page |

The Windows and Linux builds have separate dependencies and can be used independently.

---

# Windows

The Windows implementation is the more established desktop-assistant build. It uses a modular command-routing system with separate components for voice, system monitoring, tray controls, wireless functionality, notifications, productivity features, and optional AI conversation.

## Features

- Modular command routing and dispatch
- Voice input and text-to-speech
- Approximate wake-word detection
- Independent listening and speaking controls
- Windows system tray interface and local command history
- CPU, RAM, GPU, and battery monitoring
- Wi-Fi and Bluetooth controls
- Desktop notifications
- Application and browser controls
- Work profiles and reminders
- Game-mode, media, clipboard, and document command infrastructure
- Optional AI conversation system with multiple provider backends
- Telegram integration

Some registered command handlers are still scaffolds or works in progress.

## Requirements

- Windows
- Python 3.9+
- Dependencies listed in `Jarvis_Windows/requirements.txt`

For additional Windows setup information, see `Jarvis_Windows/Instructions.md`.

## Quick Start

```bash
cd Jarvis_Windows
pip install -r requirements.txt
python jarvis_main.py
```

## Architecture

```text
Jarvis_Windows/
├── jarvis_main.py
├── voice_main.py
├── GUI_Tray.py
├── system_monitor.py
├── wireless.py
├── notificationss.py
├── App_launch.py
├── Find_file.py
├── web_search.py
├── Spotify.py
├── work_saver.py
├── ai/
├── ai_convo/
└── requirements.txt
```

`jarvis_main.py` acts as the central command router. The AI conversation system is separate from normal command dispatch.

[View Windows build](./Jarvis_Windows)

---

# Linux

The Linux implementation is a rebuilt-from-scratch JARVIS for Kali and Ubuntu desktops, including virtual machines. It is text-first, with voice input and output available independently.

## Features

- Modular command routing and interactive text interface
- Application launching
- File and folder search
- System information and monitoring
- Network and Wi-Fi status and controls
- Desktop notifications
- Reminders and timers
- Web search and configurable settings
- Optional voice input and output
- Wake-word support
- Google, Vosk, and Whisper speech-to-text backends
- Piper and espeak-ng voice output
- Linux-specific platform abstraction
- Logging and safety-focused command execution

## Requirements

- Linux desktop
- Python 3.9+

Text mode requires no `pip install`.

Recommended optional system packages:

```bash
sudo apt install libnotify-bin espeak-ng plocate network-manager libgtk-3-bin
```

## Quick Start

```bash
cd Jarvis_Linux
python3 jarvis_main.py --check
python3 jarvis_main.py
```

One-shot commands:

```bash
python3 jarvis_main.py -c "system status" -c "network status"
```

## Optional Voice Support

Voice output:

```bash
sudo apt install espeak-ng
python3 jarvis_main.py --voice-out
```

Voice input:

```bash
sudo apt install portaudio19-dev python3-dev
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-voice.txt
python3 jarvis_main.py --voice
```

When using JARVIS inside a VM, audio input/output must also be enabled in the hypervisor.

## Architecture

```text
Jarvis_Linux/
├── jarvis_main.py
├── core.py
├── personality.py
├── voice.py
├── capabilities.py
├── oslayer.py
├── platform_linux.py
├── config.example.json
├── requirements.txt
├── requirements-voice.txt
└── test_jarvis.py
```

Portable capabilities are separated from Linux-specific operations through the platform layer.

## Safety

The Linux implementation:

- Refuses to run as root by default
- Does not execute arbitrary shell commands
- Does not use `shell=True`
- Does not run `sudo`, `pkexec`, `su`, or `doas`
- Does not launch desktop entries that escalate privileges
- Refuses shutdown, reboot, and logout operations
- Allows Wi-Fi controls to be disabled through configuration

## Tests

```bash
cd Jarvis_Linux
python3 -m unittest -v
```

[View Linux build](./Jarvis_Linux)

---

# Repository Structure

```text
Jarvis/
├── Jarvis_Windows/
│   ├── requirements.txt
│   └── ...
├── Jarvis_Linux/
│   ├── requirements.txt
│   ├── requirements-voice.txt
│   └── ...
├── .gitignore
├── LICENSE
└── README.md
```

The implementations intentionally keep their own dependencies and platform-specific source files.

# Development Status

JARVIS is actively being developed. The Windows implementation is the more established modular reboot and currently contains a broader collection of desktop-assistant features.

The Linux implementation is a newer rebuild focused on a clean Linux-native foundation, platform separation, and safer system interaction. Feature parity between the two implementations is not currently assumed.

# License

JARVIS is licensed under the PolyForm Noncommercial License 1.0.0.

See [LICENSE](./LICENSE) for the complete license terms.

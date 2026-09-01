🤖 JARVIS

JARVIS is a modular personal AI assistant built in Python.

This project is a reboot of an earlier JARVIS implementation that grew
into a large monolithic codebase. The reboot focuses on cleaner
architecture, better separation between components, improved
maintainability, and making the project suitable for public development.

🎯 Project Goals

The goal of the reboot is to build JARVIS as a modular system where
individual components can evolve independently.

Planned areas include:

Command routing

Voice interaction

Multiple interfaces

Tools and system actions

Memory systems

AI/model integrations

Configuration management

Logging and error handling

Security and privacy improvements

The architecture will evolve alongside the project rather than forcing
unnecessary complexity from the beginning.

🚧 Current Development

Command Routing

Command routing is one of the central foundations of JARVIS.

Commands are matched against registered rules and dispatched to the
appropriate handler based on matching type and priority.

Supported matching approaches currently include:

Exact matching

Prefix matching

Contains matching

Regular expressions

Custom matching functions

The router also provides a helper for checking which rule would match a
command without executing it.

The command router currently contains handlers covering several areas,
including:

General status and quick-info commands

Application controls

Browser/search commands

Window and system controls

Wi-Fi and Bluetooth controls

Media and Spotify-style commands

Work profiles

Reminders and checklists

Game mode

Screen/image commands

Weather, news, conversion and translation placeholders

Clipboard/document commands

Automations

Research and typing-corrector commands

Memory commands

Exams, quizzes and TODOs

Fallback handling for commands that are not handled by a registered
rule

Some handlers are currently scaffolds/TODOs. The routing infrastructure
is in place so those features can be implemented independently.

🎤 Voice Interface

Voice functionality is handled separately by voice_main.py.

Its purpose is to act as the communication layer between the user and
jarvis_main.py.

It is responsible for:

Speech input

Speech-to-text

Wake-word detection

Text-to-speech

Spoken JARVIS remarks

Listening state

Speaking state

Listening and speaking can be enabled or disabled independently, while
both can also be controlled together.

The voice system supports approximate wake-word matching, so variations
such as jarvi, jarvish, jervis, and similar pronunciations can be
recognised.

The listening flow works in two phases:

Idle mode --- JARVIS waits for a wake word.

Command mode --- after activation, commands can be spoken
without repeating the wake word until stop is spoken or the
command-mode timeout expires.

Microphone errors and unavailable microphones are handled without
crashing the main application.

Architecture

User
 │
 ├── Text Input
 │
 └── Voice Input
        │
        ▼
   jarvis_main.py
        │
        ▼
 Command Routing
        │
        ▼
 Feature Modules

🖥️ System Tray Interface

JARVIS now runs through a Windows system-tray interface implemented in
GUI_Tray.py.

The tray interface provides:

JARVIS tray icon

Type-command window

Command history

Listening controls

Speaking controls

Enable/disable both voice functions

System-monitor dashboard access

Exit/shutdown handling

The application starts the voice listener, system monitor and online
notification before placing JARVIS in the system tray.

Command Window

The type-command window allows commands to be entered without using the
microphone.

Successfully handled commands are automatically added to command
history. Duplicate commands are ignored, and up to 300 commands are
retained.

Command history is stored locally in:

command_history.json

A previous command can be selected and executed again from the history
list.

📊 System Monitor

System monitoring is implemented in system_monitor.py.

The monitor collects and stores recent system information for:

CPU usage

RAM usage

CPU temperature

GPU usage

GPU temperature

Battery percentage

Battery charging state

Battery plugged state

Battery time remaining

Battery wear percentage

Recent measurements are kept as time-series data and written to:

monitor_data.json

The default collection interval is 180 seconds, with the latest 10
measurements retained for each series.

Monitor Dashboard

The system monitor includes a Tkinter dashboard with graphical cards for
CPU, memory, temperatures, GPU load and battery information.

The dashboard refreshes automatically and displays:

Current value

Recent history

Measurement units

Last update time

Battery charging/discharging state

Estimated time remaining

Battery wear

GPU information can use NVIDIA NVML when available and falls back to
GPUtil.

CPU/RAM/battery information primarily uses psutil, while Windows WMI
is used for additional temperature and battery-health information when
available.

📶 Wi-Fi and Bluetooth Controls

Windows wireless controls are implemented in wireless.py.

The module provides:

Wi-Fi

Check Wi-Fi status

Enable Wi-Fi

Disable Wi-Fi

Toggle Wi-Fi

Wi-Fi operations use Windows netsh commands and detect common Windows
wireless-interface names.

Bluetooth

Check Bluetooth status

Enable Bluetooth

Disable Bluetooth

Toggle Bluetooth

Bluetooth operations use Windows PowerShell/PnP device commands.

These controls are intentionally Windows-specific and may require
administrator privileges depending on the system configuration.

🔔 Windows Notifications

Desktop notifications are handled by notificationss.py.

JARVIS can display:

Online notification when the assistant starts

Offline notification when the assistant shuts down

If winotify is unavailable, the notification module falls back to
printing the notification message instead of terminating the
application.

The JARVIS icon (jarvis.ico or jarvis.png) is used when available.

🧩 Project Structure

JARVIS/
│
├── jarvis_main.py
│   └── Command registration, matching and dispatch
│
├── voice_main.py
│   └── Speech recognition, wake word and text-to-speech
│
├── GUI_Tray.py
│   └── System tray, command window and voice controls
│
├── system_monitor.py
│   └── CPU/RAM/GPU/battery monitoring and dashboard
│
├── wireless.py
│   └── Windows Wi-Fi and Bluetooth controls
│
├── notificationss.py
│   └── Windows desktop notifications
│
├── jarvis.png / jarvis.ico
│   └── Optional JARVIS tray/notification icon
│
├── command_history.json
│   └── Local command history generated at runtime
│
└── monitor_data.json
    └── Local monitoring data generated at runtime

⚙️ Requirements

JARVIS is designed primarily for Windows.

Python 3.9+ is recommended.

Install the Python packages used by the current modules:

pip install SpeechRecognition pyttsx3 PyStray Pillow psutil pynvml WMI GPUtil winotify

Depending on the audio setup, SpeechRecognition may also require a
working microphone/audio backend such as PyAudio.

The project also uses Windows-native tools such as:

netsh

PowerShell

Windows PnP device management

Windows WMI

These are not Python packages and are normally supplied by Windows.

▶️ Running JARVIS

From the project directory:

python jarvis_main.py

jarvis_main.py starts the tray application through GUI_Tray.py.

You should see JARVIS running in the Windows system tray.

The tray menu provides:

Type command...

Controls...

Monitor graphs...

Listening

Speaking

Enable both

Disable both

Exit

You can also interact using the wake word and voice commands.

Example:

Jarvis

JARVIS responds with a greeting and enters command mode.

Example inline command:

Jarvis open spotify

During command mode, another wake word is not required.

To leave command mode:

stop

🧪 Development Notes

The current project intentionally separates infrastructure from
unfinished feature implementations.

The following parts are functional infrastructure:

Priority-based command registration

Multiple command matching strategies

Voice listening loop

Wake-word detection

Text-to-speech

Independent voice controls

System tray interface

Persistent command history

System monitoring

Monitoring dashboard

Wi-Fi control

Bluetooth control

Windows notifications

Graceful shutdown

Several command handlers currently print TODO or placeholder
responses. These are planned extension points rather than completed
AI/tool implementations.

🔐 Platform and Permission Notes

JARVIS currently targets Windows because several system-level features
depend on Windows APIs and commands.

Some functionality may require:

A working microphone

Internet access for Google speech recognition

Windows administrator privileges for certain device-control
operations

NVIDIA drivers/NVML for NVIDIA GPU telemetry

Optional WMI support for additional Windows hardware information

Missing optional dependencies are handled where possible so that
unrelated parts of JARVIS can continue running.

🛣️ Roadmap

Future development can build on the existing modular foundation.

Planned improvements include:

Real application launching and window control

Browser automation

Working clipboard/document tools

Weather and news integrations

Calculator and conversion tools

Translation

AI/LLM agent integration

Persistent memory

Reminders and automation engine

Research tools

Image and screen analysis

Exam/quiz assistance

Typing correction

Better security and permission handling

Configuration files

Structured logging

More interfaces beyond the system tray

The command router is designed so new functionality can be added as
independent handlers/modules without rebuilding the core architecture.

📌 Current Status

JARVIS has moved from the initial modular reboot into a working
desktop-assistant foundation.

The project now has separate components for:

Voice
  ↓
Command Router
  ↓
System / Feature Modules
  ↓
Tray Interface + Monitoring + Notifications

The main remaining work is to replace the placeholder command handlers
with real tools and connect the fallback path to the planned AI/agent
layer.
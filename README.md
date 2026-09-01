# 🤖 JARVIS

JARVIS is a modular personal AI assistant built in Python.

This project is a reboot of an earlier JARVIS implementation that grew into a large monolithic codebase. The reboot focuses on cleaner architecture, better separation between components, improved maintainability, and making the project suitable for public development.

---

## 🎯 Project Goals

The goal of the reboot is to build JARVIS as a modular system where individual components can evolve independently.

Planned areas include:

- Command routing
- Voice interaction
- Multiple interfaces
- Tools and system actions
- Memory systems
- AI/model integrations
- Configuration management
- Logging and error handling
- Security and privacy improvements

The architecture will evolve alongside the project rather than forcing unnecessary complexity from the beginning.

---

# 🚧 Current Development

## Command Routing

Command routing is one of the central foundations of JARVIS.

Commands are matched against registered rules and dispatched to the appropriate handler based on matching type and priority.

Supported matching approaches currently include:

- Exact matching
- Prefix matching
- Contains matching
- Regular expressions
- Custom matching functions

The router also provides a helper for checking which rule would match a command without executing it.

---

## 🎤 Voice Interface

Voice functionality is handled separately by `voice_main.py`.

Its purpose is to act as the communication layer between the user and `jarvis_main.py`.

It is responsible for:

- Speech input
- Speech-to-text
- Wake-word detection
- Text-to-speech
- Spoken JARVIS remarks
- Listening state
- Speaking state

Listening and speaking can be enabled or disabled independently, while both can also be controlled together.

This allows JARVIS to continue operating through text or other interfaces without requiring the microphone or voice output to remain active.

### Architecture

```text
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
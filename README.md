# 🤖 JARVIS

JARVIS is a modular personal AI assistant built in Python.

This project is a reboot of an earlier JARVIS implementation that grew into a large monolithic codebase. The reboot focuses on rebuilding the system with a cleaner architecture, better separation between components, improved maintainability, and a public-friendly configuration.

---

## 🎯 Project Goals

The goal of the reboot is to build JARVIS as a modular system where individual components can evolve independently.

Planned areas include:

- Command routing
- Multiple interfaces
- Tools and actions
- Memory systems
- AI/model integrations
- Configuration management
- Logging and error handling
- Security and privacy improvements

The architecture will evolve as the project develops rather than forcing unnecessary complexity from the beginning.

---

# 🚧 Current Development

## Command Routing

The first component being developed is the **command routing system**.

Command routing is being built first because it provides a central path for requests entering JARVIS.

Different interfaces and components can eventually send requests into the same routing system:

```text
Voice Input
     │
Telegram
     │
CLI / Other Interfaces
     │
     ▼
Command Router
     │
     ▼
Tools / Actions / AI / Other Modules
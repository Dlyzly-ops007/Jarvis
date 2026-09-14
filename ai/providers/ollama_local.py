import os
import socket

from .. import config

NAME = "ollama_local"

# Spec: local Ollama fallback is Gemma 3 ONLY — not configurable per-call.
MODEL = "gemma3"
DEFAULT_API_BASE = "http://localhost:11434"


def _api_base():
    return os.environ.get("OLLAMA_LOCAL_API_BASE", DEFAULT_API_BASE)


def is_configured():
    """Last-resort fallback: only offer it if something is actually
    listening on the configured host/port. A short-timeout TCP probe
    avoids hanging the whole fallback chain on an unreachable local
    server."""
    base = _api_base()
    try:
        host_port = base.split("//", 1)[-1].split("/", 1)[0]
        host, _, port_str = host_port.partition(":")
        port = int(port_str) if port_str else 11434
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except Exception:
        return False


def build_call_kwargs(model=None, stream=False):
    # `model` is intentionally ignored — Gemma 3 only, per spec.
    return {
        "model": f"ollama_chat/{MODEL}",
        "api_base": _api_base(),
        "stream": stream,
        "timeout": config.REQUEST_TIMEOUT,
    }

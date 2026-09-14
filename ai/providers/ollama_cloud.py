import os

from .. import config

NAME = "ollama_cloud"

DEFAULT_MODEL = "gpt-oss:20b"
DEFAULT_API_BASE = "https://ollama.com"


def is_configured():
    return bool(os.environ.get("OLLAMA_API_KEY"))


def build_call_kwargs(model=None, stream=False):
    model_name = model or os.environ.get("OLLAMA_CLOUD_MODEL", DEFAULT_MODEL)
    if not model_name.startswith("ollama_chat/"):
        model_name = f"ollama_chat/{model_name}"
    return {
        "model": model_name,
        "api_key": os.environ.get("OLLAMA_API_KEY"),
        "api_base": os.environ.get("OLLAMA_CLOUD_API_BASE", DEFAULT_API_BASE),
        "stream": stream,
        "timeout": config.REQUEST_TIMEOUT,
    }

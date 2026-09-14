import os

from .. import config

NAME = "gemini"

DEFAULT_MODEL = "gemini/gemini-2.0-flash"


def is_configured():
    return bool(os.environ.get("GEMINI_API_KEY"))


def build_call_kwargs(model=None, stream=False):
    model_name = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    if not model_name.startswith("gemini/"):
        model_name = f"gemini/{model_name}"
    return {
        "model": model_name,
        "api_key": os.environ.get("GEMINI_API_KEY"),
        "stream": stream,
        "timeout": config.REQUEST_TIMEOUT,
    }

import os

from .. import config

NAME = "groq"

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"


def is_configured():
    return bool(os.environ.get("GROQ_API_KEY"))


def build_call_kwargs(model=None, stream=False):
    model_name = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    if not model_name.startswith("groq/"):
        model_name = f"groq/{model_name}"
    return {
        "model": model_name,
        "api_key": os.environ.get("GROQ_API_KEY"),
        "stream": stream,
        "timeout": config.REQUEST_TIMEOUT,
    }

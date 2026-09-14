import os

from .. import config

NAME = "openrouter"

DEFAULT_MODEL = "openrouter/meta-llama/llama-3.3-70b-instruct"


def is_configured():
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def build_call_kwargs(model=None, stream=False):
    model_name = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    if not model_name.startswith("openrouter/"):
        model_name = f"openrouter/{model_name}"
    return {
        "model": model_name,
        "api_key": os.environ.get("OPENROUTER_API_KEY"),
        "stream": stream,
        "timeout": config.REQUEST_TIMEOUT,
    }

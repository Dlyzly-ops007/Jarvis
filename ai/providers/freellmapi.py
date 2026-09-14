import os

from .. import config

# Optional provider, per spec: "FreeLLMAPI may be added as an optional
# provider if useful." Not in DEFAULT_PROVIDER_ORDER — only used if you
# add "freellmapi" to AI_PROVIDER_ORDER yourself. Written generically so
# it works with any OpenAI-compatible endpoint, not just one vendor.

NAME = "freellmapi"

DEFAULT_MODEL = "gpt-4o-mini"


def is_configured():
    return bool(os.environ.get("FREELLMAPI_API_BASE"))


def build_call_kwargs(model=None, stream=False):
    model_name = model or os.environ.get("FREELLMAPI_MODEL", DEFAULT_MODEL)
    kwargs = {
        "model": f"openai/{model_name}",
        "api_base": os.environ.get("FREELLMAPI_API_BASE"),
        "stream": stream,
        "timeout": config.REQUEST_TIMEOUT,
    }
    api_key = os.environ.get("FREELLMAPI_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    return kwargs

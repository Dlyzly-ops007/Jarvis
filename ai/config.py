import os

# Optional: if python-dotenv is installed, load a .env file from the repo
# root so API keys don't have to be exported manually every session.
# Soft-fails like every other optional dependency in this project.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Initial configurable fallback order (spec):
#   OpenRouter -> Gemini -> Groq -> Ollama Cloud -> local Ollama (Gemma 3)
# "freellmapi" exists as a provider module but is intentionally NOT in the
# default order — add it explicitly via AI_PROVIDER_ORDER if you want it.
DEFAULT_PROVIDER_ORDER = ["openrouter", "gemini", "groq", "ollama_cloud", "ollama_local"]


def get_provider_order():
    """Provider order, configurable via AI_PROVIDER_ORDER (comma-separated)."""
    raw = os.environ.get("AI_PROVIDER_ORDER")
    if not raw:
        return list(DEFAULT_PROVIDER_ORDER)
    order = [p.strip() for p in raw.split(",") if p.strip()]
    return order or list(DEFAULT_PROVIDER_ORDER)


def _float_env(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


REQUEST_TIMEOUT = _float_env("AI_REQUEST_TIMEOUT", 30)
MAX_RETRIES_PER_PROVIDER = _int_env("AI_MAX_RETRIES", 1)

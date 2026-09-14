from . import config
from .providers import openrouter, gemini, groq, ollama_cloud, ollama_local, freellmapi

_REGISTRY = {
    "openrouter": openrouter,
    "gemini": gemini,
    "groq": groq,
    "ollama_cloud": ollama_cloud,
    "ollama_local": ollama_local,
    "freellmapi": freellmapi,
}


def get_provider(name):
    """Look up a provider module by name, or None if unknown."""
    return _REGISTRY.get(name)


def provider_names():
    """All known provider names, registry order (not fallback order)."""
    return list(_REGISTRY.keys())


def available_providers():
    """Provider modules in configured fallback order, filtered down to
    the ones that are actually usable right now (API key present /
    local server reachable)."""
    order = config.get_provider_order()
    result = []
    for name in order:
        mod = _REGISTRY.get(name)
        if mod is None:
            print(f"model_router: unknown provider in AI_PROVIDER_ORDER: {name}")
            continue
        try:
            if mod.is_configured():
                result.append(mod)
        except Exception as e:
            print(f"model_router: is_configured() failed for {name}: {e}")
    return result

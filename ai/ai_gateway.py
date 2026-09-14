import time

import litellm

from . import config, model_router


class AIGatewayError(Exception):
    """Raised when no provider is configured, or every candidate provider
    failed after retries."""


def _plain_messages(messages):
    # Keep only role/content — drop any storage metadata (timestamps,
    # provider tags, etc.) before it goes over the wire.
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def _select_candidates(provider):
    if provider:
        mod = model_router.get_provider(provider)
        if mod is None:
            raise AIGatewayError(f"unknown provider: {provider}")
        return [mod]
    return model_router.available_providers()


def _run_streaming(mod, messages, kwargs, on_token):
    text = ""
    response = litellm.completion(messages=messages, **kwargs)
    for chunk in response:
        delta = None
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            text += delta
            on_token(delta)
    return text


def _run_blocking(mod, messages, kwargs):
    response = litellm.completion(messages=messages, **kwargs)
    return response.choices[0].message.content or ""


def chat(messages, provider=None, model=None, stream=False, on_token=None):
    """Send `messages` ([{"role", "content"}, ...]) to the first working
    provider in the fallback chain (or to `provider` specifically, if
    given).

    Returns (reply_text, provider_name, resolved_model_string).
    Raises AIGatewayError if every candidate fails.
    """
    candidates = _select_candidates(provider)
    if not candidates:
        raise AIGatewayError(
            "no AI provider is configured — set at least one provider's "
            "API key (see .env.example) or run a reachable local Ollama."
        )

    plain = _plain_messages(messages)
    do_stream = bool(stream and on_token)
    errors = []

    for mod in candidates:
        for attempt in range(config.MAX_RETRIES_PER_PROVIDER + 1):
            if attempt > 0:
                time.sleep(min(2.0, 0.5 * attempt))
            try:
                kwargs = mod.build_call_kwargs(model=model, stream=do_stream)
                resolved_model = kwargs["model"]
                if do_stream:
                    text = _run_streaming(mod, plain, kwargs, on_token)
                else:
                    text = _run_blocking(mod, plain, kwargs)
                return text, mod.NAME, resolved_model
            except Exception as e:
                errors.append(f"{mod.NAME} (attempt {attempt + 1}): {e}")

    raise AIGatewayError("all AI providers failed:\n" + "\n".join(errors))

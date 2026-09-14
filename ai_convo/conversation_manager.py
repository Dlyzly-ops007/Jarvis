"""The single entry point for the Convo feature.

GUI_Tray's Convo window and the Telegram bot both call ONLY the
functions in this module — never ai_gateway or chat_store directly.
That keeps them both talking to the same storage automatically, and
keeps ai/ swappable without touching either front end.
"""

from . import chat_store
from ai import ai_gateway, model_router


class SendMessageError(Exception):
    """Raised when the user's message was saved but the AI call failed.

    Carries conv_id so callers (GUI, Telegram) can still switch to /
    display the now-non-empty conversation instead of losing track of
    it — the user's message was NOT dropped, only the reply is missing.
    """

    def __init__(self, conv_id, original_error):
        super().__init__(str(original_error))
        self.conv_id = conv_id
        self.original_error = original_error


def new_chat(title=None):
    """Create and return the id of a brand-new, empty conversation."""
    return chat_store.create_conversation(title=title)


def list_chats():
    """Sidebar/list data: id, title, created/updated — newest first."""
    return chat_store.list_conversations()


def get_chat(conv_id):
    """Full conversation (including messages), or None."""
    return chat_store.get_conversation(conv_id)


def rename_chat(conv_id, new_title):
    return chat_store.rename_conversation(conv_id, new_title)


def delete_chat(conv_id):
    return chat_store.delete_conversation(conv_id)


def search_chats(query):
    from . import search
    return search.search_conversations(query)


def provider_names():
    """Known provider names, for a UI picker (e.g. an 'auto' + these)."""
    return model_router.provider_names()


def send_message(conv_id, text, provider=None, on_token=None):
    """Send `text` as a user message in conversation `conv_id`.

    If conv_id is falsy, a new conversation is created automatically —
    this is the "no chat selected -> auto new chat" behaviour used by
    both the desktop window and Telegram.

    `provider`, if given, forces a specific provider for this message
    (still the same conversation/history either way). Otherwise the
    configured fallback chain is used.

    `on_token`, if given, is called with each streamed chunk of the
    reply as it arrives (desktop UI uses this; Telegram doesn't).

    Returns (conv_id, reply_text, provider_name, model_name).
    Raises on total AI failure — the message is still saved, so the
    conversation isn't lost, but there is no reply to append.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty message")

    if not conv_id:
        conv_id = chat_store.create_conversation()

    chat_store.append_message(conv_id, "user", text)

    conv = chat_store.get_conversation(conv_id)
    history = [{"role": m["role"], "content": m["content"]} for m in conv["messages"]]

    try:
        reply, provider_name, model_name = ai_gateway.chat(
            history, provider=provider, stream=bool(on_token), on_token=on_token
        )
    except Exception as e:
        raise SendMessageError(conv_id, e) from e

    chat_store.append_message(conv_id, "assistant", reply, provider=provider_name, model=model_name)
    return conv_id, reply, provider_name, model_name

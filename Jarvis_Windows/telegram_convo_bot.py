"""Telegram front end for the Convo system.

This is a thin adapter: all it does is map a Telegram chat_id to a
current ai_convo conversation id, and forward text to
ai_convo.conversation_manager exactly like GUI_Tray's Convo window
does. The mapping file below is NOT a chat database — no message
content lives in it, only "this Telegram chat is currently pointed at
conversation X". Actual history lives solely in ai_convo/chats/, same
as the desktop UI, so switching between Telegram and desktop for the
same conversation id sees the same history.

Runs as a background thread inside GUI_Tray's process when
TELEGRAM_BOT_TOKEN is set (see GUI_Tray.main()), so it shares that
process's ai_convo file lock with the desktop UI. It can also be run
standalone (`python telegram_convo_bot.py`) if you only want the
Telegram side — just note that running it as a *separate* process at
the same time as GUI_Tray loses the in-process lock (the JSON writes
are still atomic, but the two processes won't serialize against each
other). For a single-user desktop assistant that's a low-risk edge
case, but worth knowing.
"""

import os
import json
import threading

try:
    import telebot
except ImportError:
    telebot = None

import ai_convo.conversation_manager as convo


_HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS_PATH = os.path.join(_HERE, "ai_convo", "telegram_sessions.json")
MAX_CHATS_LISTED = 20

_bot = None
_bot_thread = None
_sessions_lock = threading.Lock()
_sessions = {}


def _load_sessions():
    global _sessions
    try:
        with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _sessions = data if isinstance(data, dict) else {}
    except FileNotFoundError:
        _sessions = {}
    except Exception as e:
        print(f"telegram_convo_bot: could not load sessions: {e}")
        _sessions = {}


def _save_sessions():
    try:
        os.makedirs(os.path.dirname(SESSIONS_PATH), exist_ok=True)
        tmp = f"{SESSIONS_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_sessions, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SESSIONS_PATH)
    except Exception as e:
        print(f"telegram_convo_bot: could not save sessions: {e}")


def _current_chat(tg_chat_id):
    with _sessions_lock:
        return _sessions.get(str(tg_chat_id))


def _set_current_chat(tg_chat_id, conv_id):
    with _sessions_lock:
        if conv_id:
            _sessions[str(tg_chat_id)] = conv_id
        else:
            _sessions.pop(str(tg_chat_id), None)
        _save_sessions()


def _build_bot():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    if telebot is None:
        raise RuntimeError("pyTelegramBotAPI not installed (pip install pyTelegramBotAPI)")

    bot = telebot.TeleBot(token, parse_mode=None)

    @bot.message_handler(commands=["start"])
    def _start(message):
        bot.reply_to(
            message,
            "JARVIS Convo.\n"
            "/newchat - start a new conversation\n"
            "/chats - list and switch conversations\n"
            "/rename <title> - rename the current conversation\n"
            "/delete - delete the current conversation\n"
            "Just send a message to chat.",
        )

    @bot.message_handler(commands=["newchat"])
    def _newchat(message):
        conv_id = convo.new_chat()
        _set_current_chat(message.chat.id, conv_id)
        bot.reply_to(message, "Started a new chat. Send a message.")

    @bot.message_handler(commands=["chats"])
    def _chats(message):
        chats = convo.list_chats()
        if not chats:
            bot.reply_to(message, "No chats yet. Send a message to start one.")
            return
        markup = telebot.types.InlineKeyboardMarkup()
        for c in chats[:MAX_CHATS_LISTED]:
            markup.add(telebot.types.InlineKeyboardButton(c["title"], callback_data=f"open:{c['id']}"))
        bot.reply_to(message, "Your chats:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("open:"))
    def _open_chat(call):
        conv_id = call.data.split(":", 1)[1]
        _set_current_chat(call.message.chat.id, conv_id)
        bot.answer_callback_query(call.id, "Switched.")
        bot.send_message(call.message.chat.id, "Continuing that chat. Send a message.")

    @bot.message_handler(commands=["rename"])
    def _rename(message):
        conv_id = _current_chat(message.chat.id)
        if not conv_id:
            bot.reply_to(message, "No active chat — use /newchat or /chats first.")
            return
        new_title = message.text.split(" ", 1)[1].strip() if " " in message.text else ""
        if not new_title:
            bot.reply_to(message, "Usage: /rename <new title>")
            return
        convo.rename_chat(conv_id, new_title)
        bot.reply_to(message, "Renamed.")

    @bot.message_handler(commands=["delete"])
    def _delete(message):
        conv_id = _current_chat(message.chat.id)
        if not conv_id:
            bot.reply_to(message, "No active chat to delete.")
            return
        convo.delete_chat(conv_id)
        _set_current_chat(message.chat.id, None)
        bot.reply_to(message, "Deleted.")

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def _on_text(message):
        conv_id = _current_chat(message.chat.id)
        try:
            new_conv_id, reply, provider, model = convo.send_message(conv_id, message.text)
        except convo.SendMessageError as e:
            _set_current_chat(message.chat.id, e.conv_id)
            bot.reply_to(message, f"AI error: {e}")
            return
        except Exception as e:
            bot.reply_to(message, f"AI error: {e}")
            return
        _set_current_chat(message.chat.id, new_conv_id)
        bot.reply_to(message, reply)

    return bot


def start_bot_in_thread():
    """Start polling in a daemon thread. Safe to call multiple times —
    a no-op if already running. Raises if TELEGRAM_BOT_TOKEN is unset
    or pyTelegramBotAPI isn't installed; callers should wrap this in a
    try/except (GUI_Tray.main() does)."""
    global _bot, _bot_thread
    if _bot_thread is not None and _bot_thread.is_alive():
        return
    _load_sessions()
    _bot = _build_bot()

    def _run():
        print("telegram_convo_bot: polling started.")
        try:
            _bot.infinity_polling(skip_pending=True)
        except Exception as e:
            print(f"telegram_convo_bot: polling stopped: {e}")

    _bot_thread = threading.Thread(target=_run, daemon=True)
    _bot_thread.start()


def stop():
    global _bot
    if _bot is not None:
        try:
            _bot.stop_polling()
        except Exception:
            pass


if __name__ == "__main__":
    start_bot_in_thread()
    import time
    print("Running standalone. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()

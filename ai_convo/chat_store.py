import os
import json
import uuid
import threading
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
CHATS_DIR = os.path.join(_HERE, "chats")
INDEX_PATH = os.path.join(CHATS_DIR, "index.json")

# One coarse lock guards every read-modify-write. Convo traffic is a
# handful of messages a minute at most (desktop + Telegram, one user) —
# a single lock keeps the file operations simple and safe without
# needing per-conversation locking.
_lock = threading.Lock()

TITLE_PREVIEW_LEN = 40
DEFAULT_TITLE = "New chat"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _ensure_dirs():
    os.makedirs(CHATS_DIR, exist_ok=True)


def _atomic_write(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _conv_path(conv_id):
    return os.path.join(CHATS_DIR, f"{conv_id}.json")


def _load_index():
    _ensure_dirs()
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"chat_store: could not load index: {e}")
        return []


def _save_index(items):
    _ensure_dirs()
    _atomic_write(INDEX_PATH, items)


def _touch_index(conv_id, title, created_at, updated_at):
    with _lock:
        items = _load_index()
        for entry in items:
            if entry["id"] == conv_id:
                entry["title"] = title
                entry["updated_at"] = updated_at
                break
        else:
            items.append({
                "id": conv_id,
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
            })
        items.sort(key=lambda e: e["updated_at"], reverse=True)
        _save_index(items)


def create_conversation(title=None):
    """Create a new, empty conversation and return its id."""
    _ensure_dirs()
    conv_id = uuid.uuid4().hex[:12]
    now = _now()
    conv = {
        "id": conv_id,
        "title": title or DEFAULT_TITLE,
        "created_at": now,
        "updated_at": now,
        "provider": None,
        "model": None,
        "messages": [],
    }
    with _lock:
        _atomic_write(_conv_path(conv_id), conv)
    _touch_index(conv_id, conv["title"], now, now)
    return conv_id


def get_conversation(conv_id):
    """Full conversation dict (including messages), or None if missing."""
    if not conv_id:
        return None
    try:
        with open(_conv_path(conv_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"chat_store: could not read {conv_id}: {e}")
        return None


def list_conversations():
    """Lightweight list for sidebars/search: id, title, timestamps —
    newest first. Does not open every conversation file."""
    return _load_index()


def append_message(conv_id, role, content, provider=None, model=None):
    """Append one message to a conversation. Returns False if the
    conversation doesn't exist."""
    with _lock:
        conv = get_conversation(conv_id)
        if conv is None:
            return False
        now = _now()
        msg = {"role": role, "content": content, "ts": now}
        if provider:
            msg["provider"] = provider
        if model:
            msg["model"] = model
        conv["messages"].append(msg)
        conv["updated_at"] = now
        if role == "assistant":
            if provider:
                conv["provider"] = provider
            if model:
                conv["model"] = model
        if role == "user" and conv["title"] in (None, "", DEFAULT_TITLE):
            conv["title"] = content.strip()[:TITLE_PREVIEW_LEN] or DEFAULT_TITLE
        _atomic_write(_conv_path(conv_id), conv)
        title, created_at, updated_at = conv["title"], conv["created_at"], conv["updated_at"]
    _touch_index(conv_id, title, created_at, updated_at)
    return True


def rename_conversation(conv_id, new_title):
    with _lock:
        conv = get_conversation(conv_id)
        if conv is None:
            return False
        new_title = (new_title or "").strip()
        if new_title:
            conv["title"] = new_title
        conv["updated_at"] = _now()
        _atomic_write(_conv_path(conv_id), conv)
        title, created_at, updated_at = conv["title"], conv["created_at"], conv["updated_at"]
    _touch_index(conv_id, title, created_at, updated_at)
    return True


def delete_conversation(conv_id):
    with _lock:
        try:
            os.remove(_conv_path(conv_id))
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"chat_store: could not delete {conv_id}: {e}")
            return False
        items = [e for e in _load_index() if e["id"] != conv_id]
        _save_index(items)
    return True

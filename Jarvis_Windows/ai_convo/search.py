from . import chat_store

# Deliberately simple (substring match over titles, then message bodies)
# per "Do NOT implement ML yet" — no embeddings/semantic search here.


def search_conversations(query):
    q = (query or "").strip().lower()
    entries = chat_store.list_conversations()
    if not q:
        return entries

    hits = []
    for entry in entries:
        if q in entry["title"].lower():
            hits.append(entry)
            continue
        conv = chat_store.get_conversation(entry["id"])
        if conv and any(q in (m.get("content") or "").lower() for m in conv.get("messages", [])):
            hits.append(entry)
    return hits

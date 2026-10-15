Runtime conversation storage for the Convo system (`ai_convo/chat_store.py`).

Each conversation is one `<id>.json` file here, plus an `index.json` for
fast listing. All of it is generated at runtime and already covered by
the repo's `*.json` `.gitignore` rule — nothing in this folder needs to
be committed.

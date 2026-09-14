"""Persistent Convo (chat) system: completely separate from Jarvis's
command dispatch, memory, and Life Engine. Desktop (GUI_Tray) and
Telegram both talk to conversation_manager, never to chat_store
directly, so there is exactly one storage path for both.
"""

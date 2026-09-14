"""AI Gateway package: provider-agnostic LLM access for Jarvis.

Nothing in here is wired into jarvis_main.dispatch(). It is only ever
called from ai_convo.conversation_manager, which is the seam the
desktop Convo window and the Telegram bot both use.
"""

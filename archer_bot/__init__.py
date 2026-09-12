"""Внутренний пакет Telegram-бота для управления TP-Link Archer C80.

Точка входа — `bot.py` в корне проекта. Здесь живут обработчики, middleware,
форматирование ответов и тексты. Логика работы с роутером — в `router_manager.py`.
"""

from __future__ import annotations

__all__ = ["constants", "formatting", "handlers", "middleware", "texts"]

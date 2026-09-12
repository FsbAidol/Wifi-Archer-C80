"""Обработчики событий бота."""

from __future__ import annotations

from archer_bot.handlers.callbacks import create_callbacks_router
from archer_bot.handlers.commands import create_commands_router

__all__ = ["create_callbacks_router", "create_commands_router"]

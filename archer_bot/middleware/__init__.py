"""Middlewares бота."""

from __future__ import annotations

from archer_bot.middleware.access import ALLOWED_USER_IDS_KEY, AccessMiddleware

__all__ = ["ALLOWED_USER_IDS_KEY", "AccessMiddleware"]

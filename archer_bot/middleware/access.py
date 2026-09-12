"""Ограничение доступа: бот отвечает только администраторам из `ADMIN_IDS`."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from archer_bot.texts import ACCESS_DENIED

logger = logging.getLogger("archer_c80_bot.access")

#: Ключ, под которым список разрешённых ID передаётся в `start_polling(...)`.
ALLOWED_USER_IDS_KEY = "allowed_user_ids"

#: Атрибуты ответа у разных типов событий.
_ANSWER_METHODS = ("answer", "reply")


class AccessMiddleware(BaseMiddleware):
    """Пропускает событие дальше только если `from_user.id` есть в белом списке.

    Остальным отправляется «Доступ запрещён», а попытка пишется в `bot.log`
    вместе с user id и username — удобно для аудита.
    """

    def __init__(self, allowed_user_ids: Iterable[int] | None = None) -> None:
        self._allowed: frozenset[int] = frozenset(allowed_user_ids or ())

    def is_allowed(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self._allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        extra_ids = data.get(ALLOWED_USER_IDS_KEY)
        allowed = self._allowed if extra_ids is None else frozenset(extra_ids)

        user = data.get("event_from_user") or getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        data["user_id"] = user_id

        if user_id is not None and user_id in allowed:
            return await handler(event, data)

        username = getattr(user, "username", None)
        logger.warning(
            "Access denied for user_id=%s username=%s event=%s",
            user_id,
            username,
            type(event).__name__,
        )
        await self._deny(event)
        return None

    @staticmethod
    async def _deny(event: TelegramObject) -> None:
        """Отвечает «Доступ запрещён», если у события есть чем ответить."""
        # CallbackQuery отличается наличием chat_instance — ему шлём уведомление.
        if hasattr(event, "chat_instance"):
            answer = getattr(event, "answer", None)
            if callable(answer):
                try:
                    await answer(text=ACCESS_DENIED, show_alert=False)
                except Exception as exc:  # noqa: BLE001 - ответ не важнее основного потока
                    logger.debug("Cannot answer callback with denial: %r", exc)
            return

        # Message и прочие события — обычный текстовый ответ.
        for method_name in _ANSWER_METHODS:
            method = getattr(event, method_name, None)
            if not callable(method):
                continue
            try:
                await method(ACCESS_DENIED)
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("Cannot reply with denial via %s: %r", method_name, exc)

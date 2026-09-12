"""Тесты AccessMiddleware: админов пропускаем, чужим — «Доступ запрещён»."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from archer_bot.middleware.access import ALLOWED_USER_IDS_KEY, AccessMiddleware

# aiogram-типы — замороженные pydantic-модели, на них нельзя навесить моки.
# Middleware работает через duck-typing (getattr по id/from_user/answer),
# поэтому подставляем лёгкие SimpleNamespace.


def _user(user_id: int, username: str = "tester") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, username=username)


def _message(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        from_user=_user(user_id),
        text="/status",
        __class__=SimpleNamespace,
    )


def _callback(user_id: int, data: str = "wifi:2g:host:1") -> SimpleNamespace:
    event = SimpleNamespace(from_user=_user(user_id), data=data)
    event.chat_instance = "ci"  # признак CallbackQuery
    return event


async def test_admin_passes_through() -> None:
    mw = AccessMiddleware([111])
    handler = AsyncMock(return_value="handled")
    event = _message(111)

    result = await mw(handler, event, {"event_from_user": _user(111)})

    assert result == "handled"
    handler.assert_awaited_once()


async def test_stranger_is_denied_message() -> None:
    mw = AccessMiddleware([111])
    handler = AsyncMock(return_value="handled")
    event = _message(999)
    event.answer = AsyncMock()

    result = await mw(handler, event, {"event_from_user": _user(999)})

    assert result is None
    handler.assert_not_awaited()
    event.answer.assert_awaited_once()
    assert "Доступ запрещён" in event.answer.await_args.args[0]


async def test_stranger_denied_uses_from_user_fallback() -> None:
    # event_from_user отсутствует — middleware берёт id из самого события
    mw = AccessMiddleware([111])
    handler = AsyncMock()
    event = _message(999)
    event.answer = AsyncMock()

    await mw(handler, event, {})
    handler.assert_not_awaited()
    event.answer.assert_awaited_once()


async def test_allowed_ids_from_workflow_data_override() -> None:
    mw = AccessMiddleware([111])
    handler = AsyncMock(return_value="ok")
    event = _message(222)

    result = await mw(handler, event, {ALLOWED_USER_IDS_KEY: frozenset({222})})
    assert result == "ok"
    handler.assert_awaited_once()


async def test_callback_stranger_gets_alert() -> None:
    mw = AccessMiddleware([111])
    handler = AsyncMock()
    event = _callback(999)
    event.answer = AsyncMock()

    result = await mw(handler, event, {"event_from_user": _user(999)})

    assert result is None
    handler.assert_not_awaited()
    event.answer.assert_awaited_once()
    # CallbackQuery получает уведомление через именованный text + show_alert
    kwargs = event.answer.await_args.kwargs
    assert "Доступ запрещён" in kwargs["text"]
    assert kwargs["show_alert"] is False


async def test_is_allowed_helper() -> None:
    mw = AccessMiddleware([111, 222])
    assert mw.is_allowed(111) is True
    assert mw.is_allowed(333) is False
    assert mw.is_allowed(None) is False


async def test_empty_whitelist_blocks_everyone() -> None:
    mw = AccessMiddleware([])
    handler = AsyncMock()
    event = _message(111)
    event.answer = AsyncMock()

    await mw(handler, event, {"event_from_user": _user(111)})
    handler.assert_not_awaited()

"""Интеграционные тесты: реальный Update прогоняется через настоящий Dispatcher.

Вместо живого Telegram используется заглушка сессии, записывающая исходящие
запросы. Это покрывает весь боевой путь: dispatch -> middleware доступа ->
обработчик -> ответ, а не только вызов функций-обработчиков напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import (
    CallbackQuery,
    Chat,
    InaccessibleMessage,
    Message,
    Update,
    User,
)
from conftest import FakeClient

import bot as bot_entry
import router_manager as rm
from config import Settings


@dataclass
class SentCall:
    method_name: str
    kwargs: dict[str, Any]


class RecordingSession(BaseSession):
    """Сессия, которая не ходит в сеть, а складывает запросы в список."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[SentCall] = []

    async def close(self) -> None:  # pragma: no cover - не используется
        return None

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        self.sent.append(SentCall(method.__api_method__, method.model_dump(warnings=False)))
        return self._fake_result(method)  # type: ignore[return-value]

    @staticmethod
    def _fake_result(method: TelegramMethod[TelegramType]) -> Any:
        name = method.__api_method__
        if name in {"sendMessage", "editMessageText"}:
            return Message(message_id=1, date=0, chat=Chat(id=1, type="private"), text="ok")
        if name == "getMe":
            return User(id=1, is_bot=True, first_name="Bot", username="archer_bot")
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""


def make_settings() -> Settings:
    return Settings(
        bot_token="1:TEST",
        admin_ids=frozenset({111}),
        router_host="192.168.0.1",
        router_password="pw",
    )


def make_bot() -> tuple[Bot, RecordingSession]:
    session = RecordingSession()
    return Bot(token="1:TEST", session=session), session


def texts_sent(session: RecordingSession, method_name: str = "sendMessage") -> list[str]:
    return [
        call.kwargs.get("text", "")
        for call in session.sent
        if call.method_name == method_name
    ]


def methods_sent(session: RecordingSession) -> list[str]:
    return [call.method_name for call in session.sent]


def make_message_update(user_id: int, text: str, update_id: int = 1) -> Update:
    message = Message(
        message_id=update_id,
        date=0,
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="T"),
        text=text,
    )
    return Update(update_id=update_id, message=message)


def make_callback_update(
    user_id: int, data: str, update_id: int, message: Message | InaccessibleMessage
) -> Update:
    callback = CallbackQuery(
        id=f"cb{update_id}",
        from_user=User(id=user_id, is_bot=False, first_name="T"),
        chat_instance="ci",
        data=data,
        message=message,
    )
    return Update(update_id=update_id, callback_query=callback)


@pytest.fixture
def harness():
    """Собирает диспетчер на подставном роутере; возвращает (bot, session, dp, client, settings)."""
    settings = make_settings()
    client = FakeClient()
    manager = rm.RouterManager(
        host=settings.router_host,
        password=settings.router_password,
        client_factory=lambda *a, **k: client,
    )
    dp = bot_entry.create_dispatcher(manager, settings)
    bot, session = make_bot()
    return bot, session, dp, client, settings


async def test_admin_status_command_flows_through_dispatcher(harness) -> None:
    bot, session, dp, client, settings = harness

    await dp.feed_update(
        bot, make_message_update(111, "/status"), allowed_user_ids=settings.admin_ids
    )

    assert any("Статус роутера" in t for t in texts_sent(session))
    assert client.authorized is True


async def test_stranger_blocked_by_middleware(harness) -> None:
    bot, session, dp, client, settings = harness

    await dp.feed_update(
        bot, make_message_update(999, "/status"), allowed_user_ids=settings.admin_ids
    )

    assert texts_sent(session) == ["🚫 Доступ запрещён."]
    # до роутера дело не дошло
    assert "get_status" not in client.calls


async def test_wifi_toggle_callback_flows_through_dispatcher(harness) -> None:
    bot, session, dp, client, settings = harness
    from tplinkrouterc6u.common.package_enum import Connection

    message = Message(message_id=10, date=0, chat=Chat(id=111, type="private"), text="old")
    update = make_callback_update(111, "wifi:5g:host:1", 2, message)

    await dp.feed_update(bot, update, allowed_user_ids=settings.admin_ids)

    assert client.wifi_calls == [(Connection.HOST_5G, True)]
    assert "editMessageText" in methods_sent(session)


async def test_reboot_confirm_callback(harness) -> None:
    bot, session, dp, client, settings = harness

    message = Message(message_id=11, date=0, chat=Chat(id=111, type="private"), text="confirm?")
    update = make_callback_update(111, "reboot:yes", 3, message)

    await dp.feed_update(bot, update, allowed_user_ids=settings.admin_ids)

    assert client.rebooted == 1


async def test_stale_callback_on_inaccessible_message_does_not_crash(harness) -> None:
    bot, session, dp, client, settings = harness

    stale = InaccessibleMessage(chat=Chat(id=111, type="private"), message_id=99)
    update = make_callback_update(111, "status:refresh", 4, stale)

    # Не должно бросить наружу: статус читается, edit недоступен -> шлём уведомление.
    await dp.feed_update(bot, update, allowed_user_ids=settings.admin_ids)

    assert "get_status" in client.calls
    assert "answerCallbackQuery" in methods_sent(session)
    assert "editMessageText" not in methods_sent(session)

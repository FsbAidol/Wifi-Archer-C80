"""Тесты обработчиков команд и callback'ов на подставном RouterManager."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.filters import CommandObject
from conftest import FakeClient

import router_manager as rm
from archer_bot.handlers import callbacks as cb
from archer_bot.handlers import commands as cmd
from archer_bot.handlers.helpers import (
    parse_reboot_action,
    parse_wifi_action,
    wifi_keyboard,
)


def make_manager(client: FakeClient) -> rm.RouterManager:
    return rm.RouterManager(
        host=client.host,
        password=client.password,
        client_factory=lambda *a, **k: client,
        logger_=__import__("logging").getLogger("test"),
    )


def make_message(text: str = "/status", user_id: int = 111) -> SimpleNamespace:
    """Лёгкая подставка Message: нужны только .answer и .from_user."""
    message = SimpleNamespace()
    message.text = text
    message.from_user = SimpleNamespace(id=user_id, username="tester")
    message.answer = AsyncMock()
    return message


def answered_text(message: SimpleNamespace) -> str:
    return "\n".join(call.args[0] for call in message.answer.await_args_list)


# --- простые команды --------------------------------------------------------


async def test_cmd_start_lists_commands() -> None:
    message = make_message()
    await cmd.cmd_start(message)
    text = answered_text(message)
    assert "/status" in text and "/wifi" in text


async def test_cmd_myid_shows_id() -> None:
    message = make_message(user_id=12345)
    await cmd.cmd_myid(message)
    assert "12345" in answered_text(message)


async def test_cmd_status_renders_and_attaches_keyboard() -> None:
    client = FakeClient()
    message = make_message()
    await cmd.cmd_status(message, make_manager(client))

    kwargs = message.answer.await_args.kwargs
    text = message.answer.await_args.args[0]
    assert "Статус роутера" in text
    assert kwargs.get("reply_markup") is not None


async def test_cmd_status_reports_connection_error() -> None:
    client = FakeClient(authorize_error=rm.ClientException("Network error: down"))
    client.fail_with = ConnectionError("down")
    client.fail_first_n = {"get_status": 99}
    message = make_message()

    await cmd.cmd_status(message, make_manager(client))
    assert "Не удалось подключиться" in answered_text(message)


async def test_cmd_info_shows_hardware_version() -> None:
    client = FakeClient()
    message = make_message()
    await cmd.cmd_info(message, make_manager(client))
    text = answered_text(message)
    assert "2.20" in text and "Archer C80" in text


async def test_cmd_ip_shows_wan() -> None:
    client = FakeClient()
    message = make_message()
    await cmd.cmd_ip(message, make_manager(client))
    assert "93.184.216.34" in answered_text(message)


async def test_cmd_leases() -> None:
    client = FakeClient()
    message = make_message()
    await cmd.cmd_leases(message, make_manager(client))
    assert "laptop" in answered_text(message)


# --- Wi-Fi команды ----------------------------------------------------------


async def test_cmd_wifi_on_switches_band() -> None:
    client = FakeClient()
    message = make_message()
    await cmd.cmd_wifi_on(message, CommandObject(command="wifi_on", args="5g"), make_manager(client))

    from tplinkrouterc6u.common.package_enum import Connection

    assert client.wifi_calls == [(Connection.HOST_5G, True)]
    assert "5 GHz" in answered_text(message)


async def test_cmd_wifi_off_bad_band() -> None:
    client = FakeClient()
    message = make_message()
    await cmd.cmd_wifi_off(message, CommandObject(command="wifi_off", args="6g"), make_manager(client))
    assert "2g" in answered_text(message)  # подсказка про допустимые диапазоны


# --- ping -------------------------------------------------------------------


async def test_cmd_ping_no_args_shows_usage() -> None:
    message = make_message()
    settings = SimpleNamespace(ping_count=2)
    await cmd.cmd_ping(message, CommandObject(command="ping", args=None), None, settings)
    assert "/ping 8.8.8.8" in answered_text(message)


async def test_cmd_ping_localhost() -> None:
    message = make_message()
    settings = SimpleNamespace(ping_count=2)
    await cmd.cmd_ping(message, CommandObject(command="ping", args="127.0.0.1"), None, settings)
    assert "ping 127.0.0.1" in answered_text(message)


async def test_cmd_ping_rejects_injection() -> None:
    message = make_message()
    settings = SimpleNamespace(ping_count=2)
    await cmd.cmd_ping(message, CommandObject(command="ping", args="8.8.8.8; rm -rf /"), None, settings)
    text = answered_text(message)
    assert "Некорректная цель" in text


# --- reboot -----------------------------------------------------------------


async def test_cmd_reboot_asks_confirmation() -> None:
    message = make_message()
    await cmd.cmd_reboot(message)
    kwargs = message.answer.await_args.kwargs
    assert kwargs.get("reply_markup") is not None
    assert "Перезагрузить роутер" in message.answer.await_args.args[0]


# --- callback: разбор данных ------------------------------------------------


def test_parse_wifi_action() -> None:
    action = parse_wifi_action("wifi:2g:host:1")
    assert action is not None and action.enable is True and action.guest is False
    assert parse_wifi_action("wifi:5g:guest:0").guest is True
    assert parse_wifi_action("wifi:9g:host:1") is None
    assert parse_wifi_action("garbage") is None


def test_parse_reboot_action() -> None:
    assert parse_reboot_action("reboot:yes").confirmed is True
    assert parse_reboot_action("reboot:no").confirmed is False
    assert parse_reboot_action("reboot:maybe") is None


def test_wifi_keyboard_has_buttons() -> None:
    status = SimpleNamespace(wifi_2g_enable=True, wifi_5g_enable=False)
    markup = wifi_keyboard(status)
    flat = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("5 GHz" in t for t in flat)


# --- callback: обработка ----------------------------------------------------


def make_callback(data: str, user_id: int = 111) -> SimpleNamespace:
    callback = SimpleNamespace()
    callback.data = data
    callback.from_user = SimpleNamespace(id=user_id)
    callback.answer = AsyncMock()
    message = SimpleNamespace()
    message.edit_text = AsyncMock()
    callback.message = message
    return callback


async def test_cb_wifi_toggles_and_edits() -> None:
    client = FakeClient()
    callback = make_callback("wifi:5g:host:1")

    await cb.cb_wifi(callback, make_manager(client))

    from tplinkrouterc6u.common.package_enum import Connection

    assert client.wifi_calls == [(Connection.HOST_5G, True)]
    callback.message.edit_text.assert_awaited()
    callback.answer.assert_awaited()


async def test_cb_wifi_bad_data_alerts() -> None:
    callback = make_callback("wifi:9g:host:1")
    await cb.cb_wifi(callback, make_manager(FakeClient()))
    kwargs = callback.answer.await_args.kwargs
    assert kwargs.get("show_alert") is True


async def test_cb_wifi_error_shows_alert() -> None:
    client = FakeClient(fail_first_n={"set_wifi": 99}, fail_with=ConnectionError("down"))
    callback = make_callback("wifi:2g:host:0")
    await cb.cb_wifi(callback, make_manager(client))
    # ошибка -> alert, сообщение не редактируется
    callback.answer.assert_awaited()
    callback.message.edit_text.assert_not_awaited()


async def test_cb_reboot_confirm_reboots() -> None:
    client = FakeClient()
    callback = make_callback("reboot:yes")
    await cb.cb_reboot(callback, make_manager(client))
    assert client.rebooted == 1
    callback.message.edit_text.assert_awaited()


async def test_cb_reboot_cancel() -> None:
    client = FakeClient()
    callback = make_callback("reboot:no")
    await cb.cb_reboot(callback, make_manager(client))
    assert client.rebooted == 0
    callback.message.edit_text.assert_awaited()


async def test_cb_status_refresh() -> None:
    client = FakeClient()
    callback = make_callback("status:refresh")
    await cb.cb_status_refresh(callback, make_manager(client))
    callback.message.edit_text.assert_awaited()


async def test_cb_unknown() -> None:
    callback = make_callback("something:else")
    await cb.cb_unknown(callback)
    callback.answer.assert_awaited()

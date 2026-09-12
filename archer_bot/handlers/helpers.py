"""Общие утилиты обработчиков: клавиатуры, отправка ошибок, разбор callback-данных."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from archer_bot.constants import CALLBACK_ALERT_LIMIT
from archer_bot.formatting import split_text
from archer_bot.texts import ERROR_TEXT_TEMPLATE
from router_manager import BANDS, Band, RouterError

logger = logging.getLogger("archer_c80_bot.handlers")


@dataclass(frozen=True)
class WifiAction:
    """Разобранная callback-строка вида `wifi:2g:host:1`."""

    band: Band
    enable: bool
    guest: bool = False


@dataclass(frozen=True)
class RebootAction:
    """Разобранная callback-строка вида `reboot:yes`."""

    confirmed: bool


def wifi_keyboard(status: Any = None) -> InlineKeyboardMarkup:
    """Панель Wi-Fi: кнопки показывают текущее состояние и противоположное действие."""
    builder = InlineKeyboardBuilder()
    for band in BANDS.values():
        state = getattr(status, f"wifi_{band.key}_enable", None)
        if state is None:
            builder.button(text=f"{band.label}: состояние ?", callback_data=f"wifi:{band.key}:host:0")
            builder.button(text=f"{band.label}: состояние ?", callback_data=f"wifi:{band.key}:host:1")
            continue
        if state:
            builder.button(text=f"🔴 Выключить {band.label}", callback_data=f"wifi:{band.key}:host:0")
        else:
            builder.button(text=f"🟢 Включить {band.label}", callback_data=f"wifi:{band.key}:host:1")
    builder.button(text="📊 Обновить статус", callback_data="status:refresh")
    builder.adjust(1)
    return builder.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения перезагрузки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, перезагрузить", callback_data="reboot:yes")
    builder.button(text="❌ Отмена", callback_data="reboot:no")
    builder.adjust(1)
    return builder.as_markup()


def parse_wifi_action(data: str) -> WifiAction | None:
    """`wifi:<band>:<host|guest>:<0|1>` -> `WifiAction` (None, если формат не наш)."""
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "wifi":
        return None
    band = BANDS.get(parts[1].lower())
    if band is None:
        return None
    return WifiAction(band=band, enable=parts[3] == "1", guest=parts[2].lower() == "guest")


def parse_reboot_action(data: str) -> RebootAction | None:
    """`reboot:yes` / `reboot:no` -> `RebootAction`."""
    parts = data.split(":")
    if len(parts) != 2 or parts[0] != "reboot":
        return None
    if parts[1] not in {"yes", "no"}:
        return None
    return RebootAction(confirmed=parts[1] == "yes")


def error_text(error: Exception) -> str:
    """Сообщение об ошибке для пользователя (без трейсбеков)."""
    if isinstance(error, RouterError):
        return ERROR_TEXT_TEMPLATE.format(details=error.user_message)
    logger.exception("Unhandled error in handler", exc_info=error)
    return ERROR_TEXT_TEMPLATE.format(
        details="Внутренняя ошибка бота. Подробности записаны в bot.log."
    )


async def reply_error(message: Message, error: Exception) -> None:
    """Отправляет текст ошибки в ответ на сообщение."""
    logger.warning("Command failed: %r", error)
    for chunk in split_text(error_text(error)):
        await message.answer(chunk)


async def answer_error(callback: CallbackQuery, error: Exception) -> None:
    """Показывает ошибку всплывающим уведомлением на callback."""
    logger.warning("Callback failed: %r", error)
    details = error.user_message if isinstance(error, RouterError) else (
        "Внутренняя ошибка бота. Подробности записаны в bot.log."
    )
    if not isinstance(error, RouterError):
        logger.exception("Unhandled error in callback handler", exc_info=error)
    text = details[:CALLBACK_ALERT_LIMIT]
    try:
        await callback.answer(text=text, show_alert=True)
    except Exception as exc:  # noqa: BLE001 - уведомление не критично
        logger.debug("Cannot show alert: %r", exc)

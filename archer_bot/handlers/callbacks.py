"""Обработчики inline-кнопок (переключение Wi-Fi, подтверждение перезагрузки).

Роутер собирается фабрикой `create_callbacks_router()` (см. пояснение в
`commands.py`) — диспетчер можно безопасно пересоздавать.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from archer_bot.formatting import format_status, wifi_state_text
from archer_bot.handlers.helpers import (
    answer_error,
    parse_reboot_action,
    parse_wifi_action,
    wifi_keyboard,
)
from archer_bot.texts import REBOOT_STARTED
from router_manager import RouterManager

logger = logging.getLogger("archer_c80_bot.callbacks")


async def _edit(callback: CallbackQuery, text: str, reply_markup: object | None = None) -> bool:
    """Безопасно редактирует сообщение кнопки (оно могло стать недоступным)."""
    message = callback.message
    # Сообщение могло стать InaccessibleMessage (нет edit_text) — проверяем наличие метода.
    if message is None or not hasattr(message, "edit_text"):
        return False
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception as exc:  # noqa: BLE001 - «message is not modified» и т.п.
        logger.debug("Cannot edit message: %r", exc)
        return False


async def cb_wifi(callback: CallbackQuery, manager: RouterManager) -> None:
    """Включает/выключает диапазон и перерисовывает панель."""
    action = parse_wifi_action(callback.data or "")
    if action is None:
        logger.warning("Malformed wifi callback data: %r", callback.data)
        await callback.answer("Не понял кнопку. Откройте /wifi заново.", show_alert=True)
        return

    try:
        state = await manager.toggle_wifi(action.band, action.enable, guest=action.guest)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - показываем понятную ошибку
        await answer_error(callback, error)
        return

    note = wifi_state_text(state.band, state.enable, state.confirmed, guest=action.guest)

    # Обновляем панель по свежему статусу; если не вышло — просто уведомляем.
    try:
        status = await manager.get_status()
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        logger.warning("Cannot refresh status after wifi switch: %r", error)
        await callback.answer(note, show_alert=False)
        return

    if not await _edit(callback, format_status(status), wifi_keyboard(status)):
        await callback.answer(note, show_alert=False)
        return
    await callback.answer(note, show_alert=False)


async def cb_reboot(callback: CallbackQuery, manager: RouterManager) -> None:
    """Подтверждение или отмена перезагрузки."""
    action = parse_reboot_action(callback.data or "")
    if action is None:
        await callback.answer("Не понял кнопку.", show_alert=True)
        return

    if not action.confirmed:
        if not await _edit(callback, "❌ Перезагрузка отменена."):
            await callback.answer("Отменено")
            return
        await callback.answer("Отменено")
        return

    try:
        await manager.reboot()
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        await answer_error(callback, error)
        return

    if not await _edit(callback, REBOOT_STARTED):
        await callback.answer(REBOOT_STARTED, show_alert=True)
        return
    await callback.answer("Перезагрузка запущена")
    logger.info(
        "Reboot requested by user_id=%s",
        callback.from_user.id if callback.from_user else None,
    )


async def cb_status_refresh(callback: CallbackQuery, manager: RouterManager) -> None:
    """Кнопка «Обновить статус» на панели Wi-Fi."""
    try:
        status = await manager.get_status()
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        await answer_error(callback, error)
        return

    if not await _edit(callback, format_status(status), wifi_keyboard(status)):
        await callback.answer("Не удалось обновить сообщение", show_alert=False)
        return
    await callback.answer("Обновлено")


async def cb_unknown(callback: CallbackQuery) -> None:
    """Защита от устаревших кнопок."""
    logger.warning("Unknown callback data: %r", callback.data)
    await callback.answer("Кнопка устарела. Откройте /wifi заново.", show_alert=False)


def create_callbacks_router() -> Router:
    """Собирает свежий роутер callback'ов при каждом вызове."""
    router = Router(name="callbacks")

    router.callback_query.register(cb_wifi, F.data.startswith("wifi:"))
    router.callback_query.register(cb_reboot, F.data.startswith("reboot:"))
    router.callback_query.register(cb_status_refresh, F.data == "status:refresh")
    # Fallback на любую неизвестную кнопку — обязательно последним.
    router.callback_query.register(cb_unknown)

    return router

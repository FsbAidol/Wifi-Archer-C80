"""Команды бота (/start, /status, /wifi, /reboot, ...).

Роутер собирается фабрикой `create_commands_router()`, а не модульным
синглтоном: это позволяет безопасно создавать диспетчер более одного раза
(например, в тестах) без «Router is already attached».
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from archer_bot.formatting import (
    format_devices,
    format_firmware,
    format_ipv4_status,
    format_leases,
    format_ping,
    format_status,
    split_text,
)
from archer_bot.handlers.helpers import confirm_keyboard, reply_error, wifi_keyboard
from archer_bot.texts import (
    BOT_DESCRIPTION,
    PING_USAGE,
    REBOOT_CONFIRM,
    UNKNOWN_COMMAND,
    WIFI_PANEL_HEADER,
    WIFI_UNKNOWN_BAND,
)
from config import Settings
from router_manager import (
    PING_TARGET_RE,
    Band,
    RouterError,
    RouterManager,
    UnknownBand,
    ping_host,
    resolve_band,
)

logger = logging.getLogger("archer_c80_bot.commands")


async def _send(message: Message, text: str) -> None:
    """Отправляет текст, при необходимости разрезая его под лимит Telegram."""
    for chunk in split_text(text):
        await message.answer(chunk)


def _band_from_args(args: str | None) -> Band:
    band_arg = (args or "").strip().split()[0] if (args or "").strip() else ""
    return resolve_band(band_arg)


# --- справка и служебное ----------------------------------------------------


async def cmd_start(message: Message) -> None:
    """Приветствие и список команд."""
    await _send(message, BOT_DESCRIPTION)


async def cmd_help(message: Message) -> None:
    await _send(message, BOT_DESCRIPTION)


async def cmd_myid(message: Message) -> None:
    """Показывает Telegram User ID — его нужно добавить в ADMIN_IDS."""
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        f"🆔 Ваш Telegram User ID: <code>{user_id}</code>\n\n"
        "Добавьте его в <code>ADMIN_IDS</code> в файле <code>.env</code>, "
        "чтобы получить доступ к боту."
    )


async def cmd_id_alias(message: Message) -> None:
    await cmd_myid(message)


# --- состояние роутера ------------------------------------------------------


async def cmd_status(message: Message, manager: RouterManager) -> None:
    """Сводный статус + панель Wi-Fi."""
    try:
        status = await manager.get_status()
    except Exception as error:  # noqa: BLE001 - показываем понятную ошибку
        await reply_error(message, error)
        return

    await message.answer(format_status(status), reply_markup=wifi_keyboard(status))


async def cmd_info(message: Message, manager: RouterManager) -> None:
    """Модель, аппаратная версия (1.0 / 2.20) и прошивка."""
    try:
        firmware = await manager.get_firmware()
    except Exception as error:  # noqa: BLE001
        await reply_error(message, error)
        return

    supported = await manager.is_supported()
    await _send(message, format_firmware(firmware, host=manager.host, supported=supported))


async def cmd_ip(message: Message, manager: RouterManager) -> None:
    """Подробные сетевые параметры."""
    try:
        ipv4 = await manager.get_ipv4_status()
    except Exception as error:  # noqa: BLE001
        await reply_error(message, error)
        return

    await _send(message, format_ipv4_status(ipv4))


async def cmd_devices(message: Message, manager: RouterManager) -> None:
    """Подключённые устройства."""
    try:
        devices = await manager.get_devices()
    except Exception as error:  # noqa: BLE001
        await reply_error(message, error)
        return

    await _send(message, format_devices(devices))


async def cmd_leases(message: Message, manager: RouterManager) -> None:
    """Аренды DHCP."""
    try:
        leases = await manager.get_dhcp_leases()
    except Exception as error:  # noqa: BLE001
        await reply_error(message, error)
        return

    await _send(message, format_leases(leases))


# --- Wi-Fi ------------------------------------------------------------------


async def cmd_wifi(message: Message, manager: RouterManager) -> None:
    """Панель управления Wi-Fi."""
    try:
        status = await manager.get_status()
    except Exception as error:  # noqa: BLE001 - без статуса панель не собрать
        logger.warning("Cannot fetch status for wifi panel: %r", error)
        await reply_error(message, error)
        return

    await message.answer(WIFI_PANEL_HEADER, reply_markup=wifi_keyboard(status))


async def _switch_wifi(message: Message, manager: RouterManager, args: str | None, enable: bool) -> None:
    try:
        band = _band_from_args(args)
    except UnknownBand as error:
        await _send(message, f"{WIFI_UNKNOWN_BAND}\n\n{error.user_message}")
        return

    try:
        state = await manager.toggle_wifi(band, enable)
    except Exception as error:  # noqa: BLE001
        await reply_error(message, error)
        return

    action = "включена" if enable else "выключена"
    confirmed = ""
    if state.confirmed is None:
        confirmed = "\n\n<i>Подтвердить состояние прошивкой не удалось.</i>"
    elif not state.confirmed:
        confirmed = "\n\n⚠️ <i>Роутер пока не подтвердил изменение — проверьте /status.</i>"
    await _send(message, f"{'✅' if enable else '🚫'} Сеть {band.label} {action}.{confirmed}")


async def cmd_wifi_on(message: Message, command: CommandObject, manager: RouterManager) -> None:
    """/wifi_on 2g — включить основную сеть 2.4 GHz."""
    await _switch_wifi(message, manager, command.args, enable=True)


async def cmd_wifi_off(message: Message, command: CommandObject, manager: RouterManager) -> None:
    """/wifi_off 5g — выключить основную сеть 5 GHz."""
    await _switch_wifi(message, manager, command.args, enable=False)


# --- перезагрузка -----------------------------------------------------------


async def cmd_reboot(message: Message) -> None:
    """Запрашивает подтверждение перед перезагрузкой."""
    await message.answer(REBOOT_CONFIRM, reply_markup=confirm_keyboard())


# --- ping -------------------------------------------------------------------


async def cmd_ping(
    message: Message, command: CommandObject, manager: RouterManager, settings: Settings
) -> None:
    """/ping <host> — проверка доступности хоста с машины, где запущен бот."""
    args = (command.args or "").strip()
    if not args:
        await _send(message, PING_USAGE)
        return

    target = args.split()[0]
    if not PING_TARGET_RE.match(target):
        await _send(
            message,
            "Некорректная цель. Укажите домен или IP без пробелов, "
            "например: <code>/ping 8.8.8.8</code>",
        )
        return

    try:
        result = await ping_host(target, settings.ping_count)
    except RouterError as error:
        await reply_error(message, error)
        return
    except OSError as error:
        logger.error("ping is unavailable: %r", error)
        await _send(message, "❗ Утилита <code>ping</code> недоступна на сервере с ботом.")
        return

    await _send(message, format_ping(result))


# --- прочее -----------------------------------------------------------------


async def unknown_text(message: Message) -> None:
    """Ответ на любой нераспознанный текст."""
    await _send(message, UNKNOWN_COMMAND)


def create_commands_router() -> Router:
    """Собирает свежий роутер команд при каждом вызове."""
    router = Router(name="commands")

    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_myid, Command("myid"))
    router.message.register(cmd_id_alias, Command("id"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(cmd_info, Command("info"))
    router.message.register(cmd_ip, Command("ip"))
    router.message.register(cmd_devices, Command("devices"))
    router.message.register(cmd_leases, Command("leases"))
    router.message.register(cmd_wifi, Command("wifi"))
    router.message.register(cmd_wifi_on, Command("wifi_on"))
    router.message.register(cmd_wifi_off, Command("wifi_off"))
    router.message.register(cmd_reboot, Command("reboot"))
    router.message.register(cmd_ping, Command("ping"))
    # Fallback на любой текст — обязательно последним.
    router.message.register(unknown_text, F.text)

    return router

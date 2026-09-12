#!/usr/bin/env python3
"""Telegram-бот для управления роутером TP-Link Archer C80 (hw 1.0 / 2.20).

Запуск:
    python bot.py

Конфигурация берётся из переменных окружения или файла `.env`
(см. `.env.example`). Доступ разрешён только пользователям из `ADMIN_IDS`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from archer_bot.handlers import create_callbacks_router, create_commands_router
from archer_bot.middleware import ALLOWED_USER_IDS_KEY, AccessMiddleware
from config import ConfigError, Settings, load_settings, setup_logging
from router_manager import RouterManager

logger = logging.getLogger("archer_c80_bot")

#: Команды, которые попадут в меню Telegram (CommandStart показываем как /start).
MENU_COMMANDS: tuple[tuple[str, str], ...] = (
    ("status", "Состояние роутера"),
    ("info", "Модель и версия прошивки"),
    ("ip", "Сетевые параметры WAN/LAN"),
    ("devices", "Подключённые устройства"),
    ("leases", "Аренды DHCP"),
    ("wifi", "Управление Wi-Fi"),
    ("reboot", "Перезагрузка роутера"),
    ("ping", "Проверить доступность хоста"),
    ("myid", "Мой Telegram ID"),
    ("help", "Справка"),
)


def create_manager(settings: Settings) -> RouterManager:
    """Собирает менеджер роутера из настроек."""
    return RouterManager(
        host=settings.router_host,
        password=settings.router_password,
        username=settings.router_username,
        verify_ssl=settings.verify_ssl,
        timeout=settings.router_timeout,
        session_ttl=settings.session_ttl,
    )


def create_dispatcher(manager: RouterManager, settings: Settings) -> Dispatcher:
    """Создаёт диспетчер: роутеры обработчиков + middleware доступа.

    Роутеры создаются заново при каждом вызове, поэтому функцию можно вызывать
    повторно (в т.ч. в тестах) без конфликта «Router is already attached».
    """
    dispatcher = Dispatcher()

    commands_router = create_commands_router()
    callbacks_router = create_callbacks_router()

    dispatcher.include_router(commands_router)
    dispatcher.include_router(callbacks_router)

    # Белый список администраторов подключается ко всем роутерам:
    # посторонние получат «Доступ запрещён» ещё до вызова обработчика.
    for router in (commands_router, callbacks_router):
        router.message.middleware(AccessMiddleware(settings.admin_ids))
        router.callback_query.middleware(AccessMiddleware(settings.admin_ids))

    # Инъекция зависимостей в обработчики.
    dispatcher["manager"] = manager
    dispatcher["settings"] = settings
    return dispatcher


def create_bot(settings: Settings, *, api_url: str | None = None) -> Bot:
    """Создаёт клиента Telegram. `api_url` нужен только для тестов."""
    kwargs: dict[str, object] = {}
    if api_url:
        kwargs["base_url"] = api_url
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        **kwargs,  # type: ignore[arg-type]
    )


async def set_commands_menu(bot: Bot) -> None:
    """Заполняет меню команд в клиентах Telegram (не критично при ошибке)."""
    commands: Sequence[BotCommand] = [
        BotCommand(command=name, description=description) for name, description in MENU_COMMANDS
    ]
    try:
        await bot.set_my_commands(list(commands))
    except Exception as exc:  # noqa: BLE001 - сеть до Telegram может быть недоступна
        logger.warning("Cannot set commands menu: %r", exc)


async def run(settings: Settings, *, api_url: str | None = None) -> None:
    """Основной цикл: подключение к Telegram и long polling."""
    manager = create_manager(settings)
    bot = create_bot(settings, api_url=api_url)
    dispatcher = create_dispatcher(manager, settings)

    await set_commands_menu(bot)
    logger.info(
        "Bot started. Router: %s, admins: %s",
        settings.router_host,
        ", ".join(str(user_id) for user_id in sorted(settings.admin_ids)),
    )

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            **{ALLOWED_USER_IDS_KEY: frozenset(settings.admin_ids)},
        )
    finally:
        await manager.close()
        logger.info("Bot stopped")


def main() -> int:
    """Точка входа: конфигурация, логирование, запуск polling."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    setup_logging(settings)

    try:
        asyncio.run(run(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted by user")
        return 0
    except Exception:  # noqa: BLE001 - фиксируем фатальную ошибку в bot.log
        logger.exception("Fatal error, bot stopped")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

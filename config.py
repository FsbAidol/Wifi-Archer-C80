"""Загрузка и валидация конфигурации бота из переменных окружения / `.env`.

Все чувствительные данные (токен бота, адрес роутера, пароль) берутся только из
окружения. Файл `.env` подхватывается автоматически, если лежит рядом с `bot.py`.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from archer_bot.constants import (
    ENV_FILE,
    LOG_BACKUP_COUNT,
    LOG_FILE,
    LOG_MAX_BYTES,
    LOGGER_NAME,
    PING_DEFAULT_COUNT,
    PROJECT_ROOT,
)

ADMIN_ID_SPLIT_RE = re.compile(r"[\s,;]+")
TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on", "да"})
FALSE_VALUES = frozenset({"0", "false", "no", "n", "off", "нет"})


class ConfigError(RuntimeError):
    """Ошибка конфигурации: незаполнены или некорректны переменные окружения."""


@dataclass(frozen=True)
class Settings:
    """Неизменяемый набор настроек, собранный один раз при старте."""

    # Telegram
    bot_token: str
    admin_ids: frozenset[int]

    # Роутер
    router_host: str
    router_password: str
    router_username: str = "admin"
    verify_ssl: bool = True
    router_timeout: int = 15
    session_ttl: int = 600

    # ping
    ping_count: int = PING_DEFAULT_COUNT

    # Логирование
    log_level: str = "INFO"
    log_file: Path = LOG_FILE
    log_to_console: bool = True

    def is_admin(self, user_id: int | None) -> bool:
        """Проверка, разрешён ли доступ пользователю с таким Telegram ID."""
        return user_id is not None and user_id in self.admin_ids


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigError(
        f"{name} должен быть одним из: 1/0, true/false, yes/no, on/off. Получено: {raw!r}"
    )


def _parse_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} должен быть целым числом. Получено: {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} должен быть >= {minimum}. Получено: {value}")
    return value


def parse_admin_ids(raw: str | None) -> tuple[int, ...]:
    """Разбирает `ADMIN_IDS` вида `11111111, 22222222` (разделители: запятая, точка с запятой, пробел)."""
    if not raw or not raw.strip():
        return ()

    ids: list[int] = []
    for chunk in ADMIN_ID_SPLIT_RE.split(raw.strip()):
        if not chunk:
            continue
        try:
            user_id = int(chunk)
        except ValueError as exc:
            raise ConfigError(
                f"ADMIN_IDS: {chunk!r} не является числом. Нужны Telegram User ID через запятую."
            ) from exc
        if user_id <= 0:
            raise ConfigError(f"ADMIN_IDS: {chunk!r} не является корректным Telegram User ID.")
        if user_id not in ids:
            ids.append(user_id)
    return tuple(ids)


def load_settings(env_file: str | Path | None = ENV_FILE) -> Settings:
    """Читает `.env` (если есть) и переменные окружения, возвращает `Settings`.

    Выбрасывает `ConfigError` с перечнем всех найденных проблем.
    """
    load_dotenv(dotenv_path=str(env_file) if env_file else None, override=False)

    problems: list[str] = []

    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    if not bot_token:
        problems.append("BOT_TOKEN не задан (получите токен у @BotFather).")
    elif ":" not in bot_token:
        problems.append("BOT_TOKEN выглядит некорректно: ожидается формат '123456:AAAA...'.")

    admin_ids = parse_admin_ids(os.getenv("ADMIN_IDS"))
    if not admin_ids:
        problems.append("ADMIN_IDS не задан или пуст. Узнайте свой ID командой /myid у бота.")

    router_host = (os.getenv("ROUTER_HOST") or "").strip()
    if not router_host:
        problems.append("ROUTER_HOST не задан (например, 192.168.0.1).")

    router_password = os.getenv("ROUTER_PASSWORD") or ""
    if not router_password:
        problems.append("ROUTER_PASSWORD не задан (пароль администратора веб-интерфейса роутера).")

    log_level = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    if log_level not in logging.getLevelNamesMapping():
        problems.append(f"LOG_LEVEL: неизвестный уровень {log_level!r}.")

    try:
        settings = Settings(
            bot_token=bot_token,
            admin_ids=frozenset(admin_ids),
            router_host=router_host,
            router_password=router_password,
            router_username=(os.getenv("ROUTER_USERNAME") or "admin").strip() or "admin",
            verify_ssl=_parse_bool("ROUTER_VERIFY_SSL", True),
            router_timeout=_parse_int("ROUTER_TIMEOUT", 15),
            session_ttl=_parse_int("ROUTER_SESSION_TTL", 600, minimum=0),
            ping_count=_parse_int("PING_COUNT", PING_DEFAULT_COUNT),
            log_level=log_level,
            log_file=Path((os.getenv("LOG_FILE") or str(LOG_FILE)).strip() or LOG_FILE),
            log_to_console=_parse_bool("LOG_TO_CONSOLE", True),
        )
    except ConfigError as exc:
        problems.append(str(exc))

    if problems:
        raise ConfigError(
            "Ошибка конфигурации:\n  - "
            + "\n  - ".join(problems)
            + "\nСкопируйте .env.example в .env и заполните значения."
        )
    return settings


def setup_logging(settings: Settings) -> logging.Logger:
    """Настраивает логирование в файл `bot.log` (с ротацией) и, опционально, в консоль."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if settings.log_to_console:
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Глушим излишне болтливый логгер HTTP-сессий Telegram.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    return logger


def project_root() -> Path:
    """Корень проекта — удобно для тестов и диагностических скриптов."""
    return PROJECT_ROOT

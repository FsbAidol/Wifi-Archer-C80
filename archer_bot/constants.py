"""Общие константы бота (без конфигурации и секретов)."""

from __future__ import annotations

from pathlib import Path

# Корень проекта: .../bot/constants.py -> parents[1]
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# --- Логирование -------------------------------------------------------------
LOG_FILE: Path = PROJECT_ROOT / "bot.log"
LOG_MAX_BYTES: int = 1 * 1024 * 1024  # 1 МБ на файл
LOG_BACKUP_COUNT: int = 5  # bot.log.1 ... bot.log.5
LOGGER_NAME: str = "archer_c80_bot"

# --- Ограничения Telegram ----------------------------------------------------
# Лимит Telegram на одну строку текста inline-кнопки
BUTTON_TEXT_LIMIT: int = 64
# Лимит Telegram на текст сообщения
MESSAGE_LIMIT: int = 4096
# Лимит на текст alert у answerCallbackQuery
CALLBACK_ALERT_LIMIT: int = 200

# --- Прочее ------------------------------------------------------------------
ENV_FILE: str = ".env"
DEVICES_PER_PAGE: int = 20
LEASES_PER_PAGE: int = 20
PING_DEFAULT_COUNT: int = 4
PING_TARGET_MAX_LEN: int = 253

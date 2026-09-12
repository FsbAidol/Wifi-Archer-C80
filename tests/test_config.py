"""Тесты конфигурации: разбор ADMIN_IDS, булевых/целых значений, валидации."""

from __future__ import annotations

import pytest

import config


def test_parse_admin_ids_various_separators() -> None:
    assert config.parse_admin_ids("111, 222;333 444") == (111, 222, 333, 444)
    assert config.parse_admin_ids("  111  ") == (111,)
    assert config.parse_admin_ids("111,111,222") == (111, 222)  # дедупликация
    assert config.parse_admin_ids("") == ()
    assert config.parse_admin_ids(None) == ()


def test_parse_admin_ids_rejects_garbage() -> None:
    with pytest.raises(config.ConfigError):
        config.parse_admin_ids("123, abc")
    with pytest.raises(config.ConfigError):
        config.parse_admin_ids("-5")


def test_load_settings_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "42:AAA")
    monkeypatch.setenv("ADMIN_IDS", "111,222")
    monkeypatch.setenv("ROUTER_HOST", "192.168.0.1")
    monkeypatch.setenv("ROUTER_PASSWORD", "pw")
    monkeypatch.setenv("ROUTER_VERIFY_SSL", "false")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    # .env не должен подмешиваться в тест
    settings = config.load_settings(env_file=None)

    assert settings.bot_token == "42:AAA"
    assert settings.admin_ids == frozenset({111, 222})
    assert settings.verify_ssl is False
    assert settings.log_level == "DEBUG"
    assert settings.is_admin(111) is True
    assert settings.is_admin(999) is False
    assert settings.is_admin(None) is False


@pytest.mark.parametrize(
    "env",
    [
        {},  # ничего не задано
        {"BOT_TOKEN": "no-colon-token"},  # некорректный токен
        {"BOT_TOKEN": "1:a", "ADMIN_IDS": "111"},  # нет роутера
        {"BOT_TOKEN": "1:a", "ADMIN_IDS": "111", "ROUTER_HOST": "1.2.3.4"},  # нет пароля
        {"BOT_TOKEN": "1:a", "ADMIN_IDS": "x", "ROUTER_HOST": "1.2.3.4", "ROUTER_PASSWORD": "p"},
        {"BOT_TOKEN": "1:a", "ADMIN_IDS": "111", "ROUTER_HOST": "1.2.3.4",
         "ROUTER_PASSWORD": "p", "ROUTER_VERIFY_SSL": "maybe"},
        {"BOT_TOKEN": "1:a", "ADMIN_IDS": "111", "ROUTER_HOST": "1.2.3.4",
         "ROUTER_PASSWORD": "p", "LOG_LEVEL": "VERBOSE"},
    ],
)
def test_load_settings_rejects_bad_config(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    for key in (
        "BOT_TOKEN", "ADMIN_IDS", "ROUTER_HOST", "ROUTER_PASSWORD",
        "ROUTER_VERIFY_SSL", "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(config.ConfigError):
        config.load_settings(env_file=None)


def test_env_example_is_loadable() -> None:
    """Регрессия: `.env.example` копируют дословно — он обязан проходить валидацию.

    Защищает шаблон от поломки (например, `ROUTER_TIMEOUT=abc` или удалённый
    обязательный ключ): пользователи делают `cp .env.example .env` и сразу
    запускают бота.
    """
    import os
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    assert example.exists(), "нет файла .env.example"

    # Изолируемся от реального окружения, чтобы значения брались из шаблона.
    keys = [
        "BOT_TOKEN", "ADMIN_IDS", "ROUTER_HOST", "ROUTER_PASSWORD", "ROUTER_USERNAME",
        "ROUTER_VERIFY_SSL", "ROUTER_TIMEOUT", "ROUTER_SESSION_TTL", "PING_COUNT",
        "LOG_LEVEL", "LOG_FILE", "LOG_TO_CONSOLE",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        settings = config.load_settings(env_file=example)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    # Значения шаблона разбираются в ожидаемые типы.
    assert settings.admin_ids == frozenset({111111111, 222222222})
    assert settings.router_host == "192.168.0.1"
    assert settings.router_username == "admin"
    assert settings.verify_ssl is True
    assert settings.router_timeout == 15
    assert settings.session_ttl == 600
    assert settings.ping_count == 4


def test_setup_logging_creates_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:a")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("ROUTER_HOST", "1.2.3.4")
    monkeypatch.setenv("ROUTER_PASSWORD", "p")
    settings = config.load_settings(env_file=None)

    log_file = tmp_path / "sub" / "bot.log"
    object.__setattr__(settings, "log_file", log_file)
    logger = config.setup_logging(settings)
    logger.info("hello from test")
    for handler in logger.handlers:
        handler.flush()

    assert log_file.exists()
    assert "hello from test" in log_file.read_text(encoding="utf-8")

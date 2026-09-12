"""Инкапсуляция работы с TP-Link Archer C80 через библиотеку `tplinkrouterc6u`.

Клиент `tplinkrouterc6u` синхронный (построен на `requests`), поэтому каждый
запрос к роутеру выполняется в отдельном потоке (`asyncio.to_thread`), а доступ к
сессии сериализуется через `asyncio.Lock` — роутер не любит параллельные
обращения по одной авторизованной сессии.

Модуль ничего не знает про Telegram: наверх отдаются готовые dataclass'ы
библиотеки либо исключение `RouterCallError` с понятным человеку текстом.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

try:  # pragma: no cover - импорт проверяется при старте приложения
    from requests import exceptions as requests_exceptions
    from tplinkrouterc6u import TplinkC80Router
    from tplinkrouterc6u.common.dataclass import (
        Device,
        Firmware,
        IPv4DHCPLease,
        IPv4Reservation,
        IPv4Status,
        Status,
    )
    from tplinkrouterc6u.common.exception import AuthorizeError, ClientException
    from tplinkrouterc6u.common.package_enum import Connection
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "Не установлены зависимости. Выполните: pip install -r requirements.txt"
    ) from exc

logger = logging.getLogger("archer_c80_bot.router")

#: Текст, который пользователь увидит, если до роутера не удалось достучаться.
CONNECTION_ERROR_TEXT = (
    "Не удалось подключиться к роутеру. Проверьте IP и пароль.\n\n"
    "Чек-лист:\n"
    "• роутер включён и доступен из сети, где запущен бот;\n"
    "• ROUTER_HOST совпадает с адресом веб-интерфейса (обычно 192.168.0.1);\n"
    "• ROUTER_PASSWORD — пароль администратора, заданный в настройках роутера;\n"
    "• для HTTPS-доступа при самоподписанном сертификате поставьте ROUTER_VERIFY_SSL=false."
)

AUTH_ERROR_TEXT = (
    "Роутер отклонил авторизацию. Проверьте ROUTER_PASSWORD: нужен пароль "
    "администратора из веб-интерфейса (обычно логин — admin)."
)

GENERIC_ERROR_TEXT = "Роутер вернул ошибку. Повторите команду позже."

NOT_IMPLEMENTED_TEXT = "Эта прошивка Archer C80 не поддерживает данную операцию."

#: Ошибки, при которых имеет смысл переподключиться и повторить запрос один раз
#: (сессия на роутере могла «протухнуть» или роутер перезагрузился).
RETRIABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    ClientException,
    requests_exceptions.RequestException,
)


class RouterError(Exception):
    """Базовое исключение слоя работы с роутером."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.user_message = message
        self.cause = cause


class RouterConnectionError(RouterError):
    """Роутер недоступен по сети / не отвечает / отклонил авторизацию."""


class RouterCallError(RouterError):
    """Запрос к роутеру не удался (ошибка протокола, прошивка, таймаут)."""


class RouterFeatureNotSupported(RouterError):
    """Операция не поддерживается клиентом или прошивкой."""


class InvalidPingTarget(RouterError):
    """Цель для /ping не похожа на домен или IP-адрес."""


class UnknownBand(RouterError):
    """Передан неизвестный диапазон Wi-Fi."""


@dataclass(frozen=True)
class Band:
    """Диапазон Wi-Fi Archer C80: основная сеть и гостевая."""

    key: str
    label: str
    host: Connection
    guest: Connection | None = None


# Archer C80 (hw 1.0 и 2.20) — двухдиапазонный AC1900, 6 GHz у него нет.
BANDS: dict[str, Band] = {
    "2g": Band(key="2g", label="2.4 GHz", host=Connection.HOST_2G, guest=Connection.GUEST_2G),
    "5g": Band(key="5g", label="5 GHz", host=Connection.HOST_5G, guest=Connection.GUEST_5G),
}
BAND_ALIASES: dict[str, str] = {
    "2g": "2g",
    "2.4": "2g",
    "2.4g": "2g",
    "2.4ghz": "2g",
    "5g": "5g",
    "5": "5g",
    "5ghz": "5g",
}


@dataclass(frozen=True)
class WifiState:
    """Состояние Wi-Fi после переключения (подтверждается повторным чтением статуса)."""

    band: Band
    target: Connection
    enable: bool
    confirmed: bool | None = None


def resolve_band(raw: str | None) -> Band:
    """Превращает пользовательскую строку (`2g`, `2.4`, `5g`, ...) в `Band`."""
    if not raw or not raw.strip():
        raise UnknownBand("Укажите диапазон: 2g или 5g.")
    key = BAND_ALIASES.get(raw.strip().lower())
    if key is None:
        raise UnknownBand(
            f"Неизвестный диапазон {raw!r}. Поддерживаются: 2g (2.4 GHz) и 5g (5 GHz)."
        )
    return BANDS[key]


def _wrap_error(action: str, exc: BaseException) -> RouterError:
    """Маппит исключение библиотеки/сети на исключение с человекочитаемым текстом."""
    detail = " ".join(str(exc).split())
    if len(detail) > 300:
        detail = detail[:297] + "..."

    if isinstance(exc, RouterError):
        return exc
    if isinstance(exc, NotImplementedError):
        return RouterFeatureNotSupported(NOT_IMPLEMENTED_TEXT, cause=exc)
    if isinstance(exc, AuthorizeError):
        logger.error("Authorize error while %s: %s", action, exc)
        return RouterConnectionError(AUTH_ERROR_TEXT, cause=exc)
    if isinstance(exc, (ConnectionError, TimeoutError, requests_exceptions.RequestException)):
        logger.error("Network error while %s: %s", action, exc)
        return RouterConnectionError(f"{CONNECTION_ERROR_TEXT}\n\nДетали: {detail}", cause=exc)
    if isinstance(exc, ClientException):
        text = str(exc)
        lowered = text.lower()
        if "network error" in lowered or "timed out" in lowered or "timeout" in lowered:
            return RouterConnectionError(f"{CONNECTION_ERROR_TEXT}\n\nДетали: {detail}", cause=exc)
        if "login failed" in lowered or "password" in lowered:
            return RouterConnectionError(f"{AUTH_ERROR_TEXT}\n\nДетали: {detail}", cause=exc)
        logger.error("Client error while %s: %s", action, exc)
        return RouterCallError(f"{GENERIC_ERROR_TEXT}\n\nДетали: {detail}", cause=exc)
    if isinstance(exc, (KeyError, IndexError, ValueError, AttributeError)):
        logger.error("Unexpected router response while %s: %r", action, exc)
        return RouterCallError(
            f"{GENERIC_ERROR_TEXT} Роутер ответил в неожиданном формате ({detail}).",
            cause=exc,
        )

    logger.exception("Unexpected error while %s", action, exc_info=exc)
    return RouterCallError(f"{GENERIC_ERROR_TEXT}\n\nДетали: {detail}", cause=exc)


class RouterManager:
    """Асинхронная обёртка над синхронным `TplinkC80Router`.

    * ленивое подключение: сессия создаётся при первом запросе;
    * переиспользование сессии в пределах `session_ttl` секунд;
    * один автоматический повтор с переподключением при сетевой ошибке;
    * понятные исключения вместо «сырых» трейсбеков.
    """

    def __init__(
        self,
        host: str,
        password: str,
        username: str = "admin",
        *,
        verify_ssl: bool = True,
        timeout: int = 15,
        session_ttl: int = 600,
        logger_: logging.Logger | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._host = host
        self._password = password
        self._username = username
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._session_ttl = session_ttl
        self._log = logger_ or logger
        self._client_factory = client_factory or TplinkC80Router

        self._client: Any | None = None
        self._client_created_at: float = 0.0
        self._lock = asyncio.Lock()

    # -- служебное ----------------------------------------------------------
    @property
    def host(self) -> str:
        return self._host

    @property
    def is_connected(self) -> bool:
        """Есть ли сейчас живая сессия с роутером."""
        return self._client is not None

    def _new_client(self) -> Any:
        return self._client_factory(
            self._host,
            self._password,
            self._username,
            None,
            self._verify_ssl,
            self._timeout,
        )

    def _session_expired(self) -> bool:
        if self._session_ttl <= 0:
            return True
        return (time.monotonic() - self._client_created_at) >= self._session_ttl

    def _get_client_sync(self) -> Any:
        """Создаёт/возвращает авторизованный клиент. Выполняется в потоке."""
        if self._client is not None and not self._session_expired():
            return self._client

        client = self._new_client()
        self._log.debug("Connecting to %s as %r", self._host, self._username)
        client.authorize()
        self._client = client
        self._client_created_at = time.monotonic()
        self._log.info("Authorized on router %s", self._host)
        return client

    async def _drop_session(self) -> None:
        """Сбрасывает сессию, чтобы следующий запрос авторизовался заново.

        Роутер при этом не блокируется: `logout()` тоже уходит в поток, а его
        ошибка не критична (сессия всё равно будет создана заново).
        """
        client, self._client = self._client, None
        self._client_created_at = 0.0
        if client is None:
            return
        self._log.debug("Dropping router session for %s", self._host)
        try:
            await asyncio.to_thread(client.logout)
        except Exception as exc:  # noqa: BLE001 - logout по «мёртвой» сессии ожидаемо падает
            self._log.debug("Logout while dropping session failed: %r", exc)

    async def _call(self, action: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Выполняет метод клиента в потоке с авторизацией и одним повтором."""
        async with self._lock:
            attempt = 0
            while True:
                attempt += 1
                try:
                    client = await asyncio.to_thread(self._get_client_sync)
                    bound = partial(getattr(client, method), *args, **kwargs)
                    return await asyncio.to_thread(bound)
                except Exception as exc:  # noqa: BLE001 - маппим в понятное исключение
                    await self._drop_session()
                    # Один повтор с переподключением: сессия на роутере могла
                    # «протухнуть» или роутер перезагрузился.
                    if attempt == 1 and isinstance(exc, RETRIABLE_EXCEPTIONS):
                        self._log.warning(
                            "%s failed (%s), reconnecting and retrying once",
                            action,
                            type(exc).__name__,
                        )
                        continue
                    raise _wrap_error(action, exc) from exc

    # -- публичное API ------------------------------------------------------
    async def get_firmware(self) -> Firmware:
        """Модель, аппаратная и программная версии (hw 1.0 / 2.20 и т.п.)."""
        return await self._call("get_firmware", "get_firmware")

    async def get_status(self) -> Status:
        """Сводный статус: WAN/LAN, аптайм, клиенты, состояние Wi-Fi."""
        return await self._call("get_status", "get_status")

    async def get_ipv4_status(self) -> IPv4Status:
        """Подробности IPv4: маска, шлюз, DNS, тип WAN-подключения."""
        return await self._call("get_ipv4_status", "get_ipv4_status")

    async def get_devices(self) -> list[Device]:
        """Список устройств из сводного статуса."""
        status = await self.get_status()
        return list(status.devices or [])

    async def get_dhcp_leases(self) -> list[IPv4DHCPLease]:
        """Клиенты DHCP (аренды)."""
        return await self._call("get_dhcp_leases", "get_dhcp_leases")

    async def get_ipv4_reservations(self) -> list[IPv4Reservation]:
        """Статические резервирования адресов."""
        return await self._call("get_ipv4_reservations", "get_ipv4_reservations")

    async def is_supported(self) -> bool:
        """Проверяет, отвечает ли хост протоколом Archer C80."""
        async with self._lock:
            try:
                client = await asyncio.to_thread(self._get_client_sync)
                return bool(await asyncio.to_thread(client.supports))
            except Exception as exc:  # noqa: BLE001
                self._log.warning("supports() check failed: %r", exc)
                return False

    async def set_wifi(self, connection: Connection, enable: bool) -> None:
        """Включает/выключает сеть (основную или гостевую)."""
        await self._call(f"set_wifi({connection.value} -> {enable})", "set_wifi", connection, enable)

    async def toggle_wifi(self, band: Band, enable: bool, guest: bool = False) -> WifiState:
        """Переключает Wi-Fi и подтверждает результат чтением статуса."""
        target = (band.guest if guest else band.host) or band.host
        await self.set_wifi(target, enable)

        confirmed: bool | None = None
        try:
            status = await self.get_status()
        except RouterError as exc:
            self._log.warning("Cannot confirm wifi state: %s", exc.user_message)
        else:
            confirmed = self._read_wifi_flag(status, target)
        return WifiState(band=band, target=target, enable=enable, confirmed=confirmed)

    @staticmethod
    def _read_wifi_flag(status: Status, connection: Connection) -> bool | None:
        """Достаёт из `Status` флаг конкретного диапазона (если прошивка его отдаёт)."""
        flags = {
            Connection.HOST_2G: status.wifi_2g_enable,
            Connection.HOST_5G: status.wifi_5g_enable,
            Connection.GUEST_2G: status.guest_2g_enable,
            Connection.GUEST_5G: status.guest_5g_enable,
        }
        return flags.get(connection)

    async def reboot(self) -> None:
        """Перезагружает роутер."""
        await self._call("reboot", "reboot")
        # После ребута текущая сессия гарантированно невалидна.
        await self._drop_session()

    async def close(self) -> None:
        """Корректно завершает сессию (вызывается при остановке бота)."""
        async with self._lock:
            client, self._client = self._client, None
            self._client_created_at = 0.0
            if client is None:
                return
            try:
                await asyncio.to_thread(client.logout)
                self._log.info("Logged out from router %s", self._host)
            except Exception as exc:  # noqa: BLE001
                self._log.debug("Logout failed: %r", exc)


# --- ping (не требует роутера, но удобен из того же чата) --------------------

PING_TARGET_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9\-.]{0,251}[A-Za-z0-9])?$")
_PING_TIME_RE = re.compile(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_PING_STATS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class PingResult:
    target: str
    ok: bool
    sent: int
    received: int
    avg_ms: float | None
    output: str


def _ping_args(target: str, count: int) -> list[str]:
    if platform.system().lower().startswith("win"):
        return ["ping", "-n", str(count), "-w", "2000", target]
    return ["ping", "-c", str(count), "-W", "2", target]


async def ping_host(target: str, count: int = 4) -> PingResult:
    """Пингует хост с машины, где запущен бот (без shell-инъекций: список аргументов)."""
    target = (target or "").strip().strip("[]")
    if not target or not PING_TARGET_RE.match(target):
        raise InvalidPingTarget(
            "Некорректная цель для ping. Укажите домен или IP, например: /ping 8.8.8.8"
        )

    process = await asyncio.create_subprocess_exec(
        *_ping_args(target, count),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    raw_stdout, _ = await process.communicate()
    output = raw_stdout.decode("utf-8", errors="replace").strip()

    sent = received = 0
    for line in output.splitlines():
        if "packets transmitted" in line or "Packets: Sent" in line:
            numbers = [int(n) for n in re.findall(r"\d+", line)]
            if len(numbers) >= 2:
                sent, received = numbers[0], numbers[1]
            break

    avg_ms: float | None = None
    match = _PING_STATS_RE.search(output)
    if match:
        avg_ms = float(match.group(2))
    else:
        times = [float(t) for t in _PING_TIME_RE.findall(output)]
        if times:
            received = received or len(times)
            avg_ms = sum(times) / len(times)

    sent = sent or count
    return PingResult(
        target=target,
        ok=bool(received),
        sent=sent,
        received=received,
        avg_ms=avg_ms,
        output=output,
    )

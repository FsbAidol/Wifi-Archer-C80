"""Форматирование ответов бота (HTML-разметка Telegram).

Всё, что приходит с роутера (имена устройств, SSID и т.п.), экранируется —
это одновременно защита от поломки разметки и от инъекции тегов.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Any

from tplinkrouterc6u.common.dataclass import (
    Device,
    Firmware,
    IPv4DHCPLease,
    IPv4Status,
    Status,
)
from tplinkrouterc6u.common.package_enum import Connection

from archer_bot.constants import MESSAGE_LIMIT
from router_manager import Band, PingResult

UNKNOWN = "—"

CONNECTION_LABELS: dict[Connection, str] = {
    Connection.WIRED: "кабель",
    Connection.HOST_2G: "Wi-Fi 2.4G",
    Connection.HOST_5G: "Wi-Fi 5G",
    Connection.GUEST_2G: "гостевая 2.4G",
    Connection.GUEST_5G: "гостевая 5G",
    Connection.IOT_2G: "IoT 2.4G",
    Connection.IOT_5G: "IoT 5G",
    Connection.UNKNOWN: "не определено",
}


def esc(value: Any) -> str:
    """Экранирует значение для HTML-режима Telegram."""
    if value is None:
        return UNKNOWN
    return html.escape(str(value), quote=False)


def maybe(value: Any, suffix: str = "") -> str:
    """Значение или прочерк, если роутер ничего не отдал."""
    if value is None or value == "":
        return UNKNOWN
    return f"{esc(value)}{suffix}"


def yes_no(value: bool | None) -> str:
    """Вкл/выкл в человекочитаемом виде."""
    if value is None:
        return UNKNOWN
    return "включено" if value else "выключено"


def state_mark(value: bool | None) -> str:
    """Иконка состояния: 🟢 / 🔴 / ⚪."""
    if value is None:
        return "⚪️"
    return "🟢" if value else "🔴"


def humanize_uptime(seconds: int | None) -> str:
    """3600 -> '1 ч 0 мин'."""
    if seconds is None or seconds < 0:
        return UNKNOWN
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes or not parts:
        parts.append(f"{minutes} мин")
    if not days and not hours and secs:
        parts.append(f"{secs} с")
    return " ".join(parts)


def percent(value: float | None) -> str:
    if value is None:
        return UNKNOWN
    return f"{float(value):.1f}%"


def connection_label(connection: Connection | None) -> str:
    if connection is None:
        return UNKNOWN
    return CONNECTION_LABELS.get(connection, esc(connection.value))


def format_status(status: Status) -> str:
    """Сводка по роутеру для команды /status."""
    lines: list[str] = ["<b>📊 Статус роутера</b>", ""]
    lines.append(f"🌐 <b>WAN IP:</b> {maybe(status.wan_ipv4_addr)}")
    lines.append(f"🛜 <b>LAN IP:</b> {maybe(status.lan_ipv4_addr)}")
    lines.append(f"🚪 <b>Шлюз:</b> {maybe(status.wan_ipv4_gateway)}")
    lines.append(f"⏱ <b>Аптайм:</b> {humanize_uptime(status.wan_ipv4_uptime)}")

    lines.append("")
    lines.append(
        "👥 <b>Клиенты:</b> "
        f"{status.clients_total} всего"
        f" (Wi-Fi {status.wifi_clients_total}, кабель {status.wired_total}, "
        f"гостевая {status.guest_clients_total}"
        + (f", IoT {status.iot_clients_total}" if status.iot_clients_total else "")
        + ")"
    )

    wifi_lines = [
        f"  {state_mark(status.wifi_2g_enable)} 2.4 GHz — {yes_no(status.wifi_2g_enable)}",
        f"  {state_mark(status.wifi_5g_enable)} 5 GHz — {yes_no(status.wifi_5g_enable)}",
    ]
    if status.guest_2g_enable is not None or status.guest_5g_enable is not None:
        wifi_lines.append(
            f"  {state_mark(status.guest_2g_enable)} гостевая 2.4 GHz — "
            f"{yes_no(status.guest_2g_enable)}"
        )
        wifi_lines.append(
            f"  {state_mark(status.guest_5g_enable)} гостевая 5 GHz — "
            f"{yes_no(status.guest_5g_enable)}"
        )
    lines.append("")
    lines.append("<b>📶 Wi-Fi:</b>")
    lines.extend(wifi_lines)

    if status.mem_usage is not None or status.cpu_usage is not None:
        lines.append("")
        lines.append(
            f"🧠 <b>CPU:</b> {percent(status.cpu_usage)}   "
            f"💾 <b>RAM:</b> {percent(status.mem_usage)}"
        )

    if status.wan_ipv6_enabled is not None:
        lines.append(f"🌍 <b>IPv6:</b> {yes_no(status.wan_ipv6_enabled)}")
        if status.wan_ipv6_addr:
            lines.append(f"   {maybe(status.wan_ipv6_addr)}")

    return "\n".join(lines)


def format_firmware(firmware: Firmware, *, host: str, supported: bool | None = None) -> str:
    """Информация о модели и версиях (для /info)."""
    lines: list[str] = ["<b>ℹ️ Информация о роутере</b>", ""]
    lines.append(f"📦 <b>Модель:</b> {maybe(firmware.model)}")
    lines.append(f"🔧 <b>Аппаратная версия:</b> {maybe(firmware.hardware_version)}")
    lines.append(f"💽 <b>Прошивка:</b> {maybe(firmware.firmware_version)}")
    lines.append(f"🏠 <b>Адрес:</b> {esc(host)}")
    if supported is not None:
        lines.append(
            f"🧩 <b>Профиль Archer C80:</b> "
            f"{'подтверждён' if supported else 'не подтверждён'}"
        )
    lines.append("")
    lines.append(
        "<i>Поддерживаются аппаратные версии 1.0 и 2.20 — "
        "обе работают через один клиент tplinkrouterc6u.</i>"
    )
    return "\n".join(lines)


def format_ipv4_status(ipv4: IPv4Status) -> str:
    """Подробности IP-настройки для команды /ip."""
    lines: list[str] = ["<b>🧭 Сетевые параметры</b>", ""]
    lines.append(f"🌐 <b>WAN IP:</b> {maybe(ipv4.wan_ipv4_ipaddr)}")
    lines.append(f"🔗 <b>Тип WAN:</b> {maybe(ipv4.wan_ipv4_conntype)}")
    lines.append(f"🚪 <b>Шлюз:</b> {maybe(ipv4.wan_ipv4_gateway)}")
    lines.append(f"🎭 <b>Маска WAN:</b> {maybe(ipv4.wan_ipv4_netmask)}")
    lines.append(
        f"🧬 <b>DNS:</b> {maybe(ipv4.wan_ipv4_pridns)} / {maybe(ipv4.wan_ipv4_snddns)}"
    )
    lines.append("")
    lines.append(f"🏠 <b>LAN IP:</b> {maybe(ipv4.lan_ipv4_ipaddr)}")
    lines.append(f"🎭 <b>Маска LAN:</b> {maybe(ipv4.lan_ipv4_netmask)}")
    lines.append(f"🧮 <b>DHCP-сервер:</b> {yes_no(ipv4.lan_ipv4_dhcp_enable)}")
    lines.append(f"📡 <b>WAN MAC:</b> {maybe(ipv4.wan_macaddr)}")
    return "\n".join(lines)


def format_devices(devices: Sequence[Device], limit: int = 20) -> str:
    """Список подключённых устройств для команды /devices."""
    if not devices:
        return "👥 <b>Устройства</b>\n\nСейчас к роутеру никто не подключён."

    online = [device for device in devices if device.active]
    offline = [device for device in devices if not device.active]

    lines: list[str] = [
        f"👥 <b>Устройства</b> — онлайн: {len(online)}, всего: {len(devices)}",
        "",
    ]

    shown = online[:limit]
    for index, device in enumerate(shown, start=1):
        name = esc(device.hostname) or "без имени"
        speed = ""
        if device.down_speed or device.up_speed:
            speed = f" ⬇️{device.down_speed}⬆️{device.up_speed}"
        lines.append(
            f"{index}. <b>{name}</b>\n"
            f"    {maybe(device.ipaddr)} · {maybe(device.macaddr)} · "
            f"{connection_label(device.type)}{speed}"
        )

    if len(online) > len(shown):
        lines.append("")
        lines.append(f"… и ещё {len(online) - len(shown)} устройств(а).")
    if offline:
        lines.append("")
        lines.append(f"💤 Неактивных записей: {len(offline)}")
    return "\n".join(lines)


def format_leases(leases: Sequence[IPv4DHCPLease], limit: int = 20) -> str:
    """Аренды DHCP для команды /leases."""
    if not leases:
        return "🧾 <b>Аренды DHCP</b>\n\nСписок пуст."

    lines: list[str] = [f"🧾 <b>Аренды DHCP</b> — всего: {len(leases)}", ""]
    for index, lease in enumerate(leases[:limit], start=1):
        name = esc(lease.hostname) or "без имени"
        lines.append(
            f"{index}. <b>{name}</b>\n"
            f"    {maybe(lease.ipaddr)} · {maybe(lease.macaddr)} · {maybe(lease.lease_time)}"
        )
    if len(leases) > limit:
        lines.append("")
        lines.append(f"… и ещё {len(leases) - limit} записей(и).")
    return "\n".join(lines)


def format_ping(result: PingResult) -> str:
    """Результат /ping."""
    icon = "✅" if result.ok else "❌"
    avg = f"{result.avg_ms:.2f} ms" if result.avg_ms is not None else UNKNOWN
    return (
        f"{icon} <b>ping {esc(result.target)}</b>\n\n"
        f"Отправлено: {result.sent}, получено: {result.received}\n"
        f"Среднее время: {avg}"
    )


def wifi_state_text(band: Band, enable: bool, confirmed: bool | None, *, guest: bool = False) -> str:
    """Текст после переключения Wi-Fi."""
    kind = "гостевая сеть" if guest else "сеть"
    action = "включена" if enable else "выключена"
    header = f"{'✅' if enable else '🚫'} {kind} {esc(band.label)} {action}"
    if confirmed is None:
        note = "\n\n<i>Команда отправлена, но подтвердить состояние прошивкой не удалось.</i>"
    elif confirmed != enable:
        note = (
            "\n\n⚠️ <i>Роутер подтвердил другое состояние — "
            "обновите /status через несколько секунд.</i>"
        )
    else:
        note = "\n\n<i>Состояние подтверждено роутером.</i>"
    return header + note


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Режет длинный текст на части, пригодные к отправке (по строкам)."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # Строка длиннее лимита — режем её жёстко.
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks

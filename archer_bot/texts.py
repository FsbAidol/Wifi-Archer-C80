"""Тексты сообщений бота (все строки, которые видит пользователь)."""

from __future__ import annotations

ACCESS_DENIED = "🚫 Доступ запрещён."

BOT_DESCRIPTION = (
    "👋 <b>Бот управления TP-Link Archer C80</b>\n\n"
    "Поддерживаются аппаратные версии 1.0 и 2.20.\n\n"
    "<b>Команды:</b>\n"
    "/status — состояние роутера, клиенты, Wi-Fi\n"
    "/info — модель, версии прошивки и железа\n"
    "/ip — WAN/LAN параметры, DNS, маска\n"
    "/devices — список подключённых устройств\n"
    "/leases — аренды DHCP\n"
    "/wifi — панель управления Wi-Fi (2.4 / 5 GHz)\n"
    "/wifi_on 2g|5g — включить диапазон\n"
    "/wifi_off 2g|5g — выключить диапазон\n"
    "/reboot — перезагрузка роутера (с подтверждением)\n"
    "/ping 8.8.8.8 — проверка доступности хоста\n"
    "/myid — ваш Telegram User ID\n"
    "/help — эта справка"
)

WIFI_PANEL_HEADER = (
    "📶 <b>Управление Wi-Fi</b>\n\n"
    "Кнопки включают и выключают основную сеть Archer C80."
)

REBOOT_CONFIRM = (
    "⚠️ <b>Перезагрузить роутер?</b>\n\n"
    "Интернет пропадёт примерно на 1–2 минуты."
)

REBOOT_STARTED = (
    "🔄 Команда на перезагрузку отправлена.\n"
    "Роутер будет недоступен 1–2 минуты, затем попробуйте /status."
)

PING_USAGE = (
    "Укажите цель: <code>/ping 8.8.8.8</code> или <code>/ping google.com</code>"
)

COMMAND_FAILED = "❗ Команда не выполнена."

ERROR_TEXT_TEMPLATE = "❗ <b>Ошибка</b>\n\n{details}"

UNKNOWN_COMMAND = (
    "Не понимаю такую команду. Список доступных — в /help."
)

WIFI_UNKNOWN_BAND = "Укажите диапазон: <code>2g</code> или <code>5g</code>."

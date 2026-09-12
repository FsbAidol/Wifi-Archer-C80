"""Тесты форматирования ответов бота."""

from __future__ import annotations

from archer_bot import formatting
from router_manager import BANDS, PingResult


def test_esc_and_maybe() -> None:
    assert formatting.esc("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
    assert formatting.maybe(None) == formatting.UNKNOWN
    assert formatting.maybe("") == formatting.UNKNOWN
    assert formatting.maybe("ok") == "ok"
    assert formatting.maybe(5, " шт") == "5 шт"


def test_yes_no_and_state_mark() -> None:
    assert formatting.yes_no(True) == "включено"
    assert formatting.yes_no(False) == "выключено"
    assert formatting.yes_no(None) == formatting.UNKNOWN
    assert formatting.state_mark(True) == "🟢"
    assert formatting.state_mark(False) == "🔴"
    assert formatting.state_mark(None) == "⚪️"


def test_humanize_uptime() -> None:
    assert formatting.humanize_uptime(None) == formatting.UNKNOWN
    assert formatting.humanize_uptime(-1) == formatting.UNKNOWN
    assert formatting.humanize_uptime(3725) == "1 ч 2 мин"
    assert formatting.humanize_uptime(90061) == "1 д 1 ч 1 мин"
    assert formatting.humanize_uptime(45) == "0 мин 45 с"


def test_percent() -> None:
    assert formatting.percent(None) == formatting.UNKNOWN
    assert formatting.percent(12.345) == "12.3%"


def test_split_text_short_stays_whole() -> None:
    assert formatting.split_text("abc", 100) == ["abc"]


def test_split_text_long_is_chunked() -> None:
    text = "\n".join(f"line {i}" for i in range(2000))
    chunks = formatting.split_text(text, 100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    # склейка не теряет строки
    assert "\n".join(chunks) == text


def test_format_status_contains_key_fields() -> None:
    class FakeStatus:
        wan_ipv4_addr = "93.184.216.34"
        lan_ipv4_addr = "192.168.0.1"
        wan_ipv4_gateway = "10.0.0.1"
        wan_ipv4_uptime = 3725
        clients_total = 3
        wifi_clients_total = 2
        wired_total = 1
        guest_clients_total = 0
        iot_clients_total = None
        wifi_2g_enable = True
        wifi_5g_enable = False
        guest_2g_enable = None
        guest_5g_enable = None
        mem_usage = 42.0
        cpu_usage = 13.5
        wan_ipv6_enabled = None
        wan_ipv6_addr = None

    text = formatting.format_status(FakeStatus())
    assert "93.184.216.34" in text
    assert "1 ч 2 мин" in text
    assert "🟢 2.4 GHz" in text
    assert "🔴 5 GHz" in text
    assert "42.0%" in text


def test_format_ping_ok_and_fail() -> None:
    ok = PingResult("8.8.8.8", ok=True, sent=4, received=4, avg_ms=12.5, output="...")
    assert "✅" in formatting.format_ping(ok)
    assert "12.50 ms" in formatting.format_ping(ok)

    bad = PingResult("bad", ok=False, sent=4, received=0, avg_ms=None, output="...")
    assert "❌" in formatting.format_ping(bad)


def test_format_devices_empty_and_full() -> None:
    assert "никто не подключён" in formatting.format_devices([])

    class FakeDevice:
        active = True
        hostname = "<tv>"
        ipaddr = "192.168.0.5"
        macaddr = "AA:BB:CC:DD:EE:FF"
        type = None
        down_speed = 10
        up_speed = 5

    text = formatting.format_devices([FakeDevice()])
    assert "&lt;tv&gt;" in text  # экранирование
    assert "192.168.0.5" in text


def test_wifi_state_text_variants() -> None:
    band = BANDS["2g"]
    assert "подтверждено роутером" in formatting.wifi_state_text(band, True, True)
    assert "не удалось" in formatting.wifi_state_text(band, True, None)
    assert "другое состояние" in formatting.wifi_state_text(band, True, False)

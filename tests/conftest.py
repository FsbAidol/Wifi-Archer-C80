"""Общий тестовый инвентарь: подставной клиент роутера и фабрики событий."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from router_manager import ClientException


class FakeClient:
    """Подставка вместо `TplinkC80Router` с программируемым поведением.

    Считает вызовы и может выбрасывать заданные исключения, чтобы проверить
    обработку ошибок и логику повтора в `RouterManager`.
    """

    def __init__(
        self,
        *,
        host: str = "192.168.0.1",
        password: str = "secret",
        authorize_error: Exception | None = None,
        fail_first_n: dict[str, int] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self.host = host
        self.password = password
        self.authorize_error = authorize_error
        self.fail_first_n = dict(fail_first_n or {})
        self.fail_with = fail_with
        self.calls: list[str] = []
        self.authorized = False
        self.logged_out = 0
        self.wifi_calls: list[tuple[object, bool]] = []
        self.rebooted = 0
        # Текущее состояние диапазонов (меняется через set_wifi, читается в get_status)
        from tplinkrouterc6u.common.package_enum import Connection

        self._wifi_states: dict[object, bool] = {
            Connection.HOST_2G: True,
            Connection.HOST_5G: False,
            Connection.GUEST_2G: False,
            Connection.GUEST_5G: False,
        }

    # --- lifecycle ---
    def authorize(self) -> None:
        self.calls.append("authorize")
        if self.authorize_error is not None:
            raise self.authorize_error
        self.authorized = True

    def logout(self) -> None:
        self.calls.append("logout")
        self.logged_out += 1

    def supports(self) -> bool:
        self.calls.append("supports")
        return True

    # --- helpers ---
    def _maybe_fail(self, name: str) -> None:
        remaining = self.fail_first_n.get(name, 0)
        if remaining > 0:
            self.fail_first_n[name] = remaining - 1
            raise self.fail_with or ClientException("Network error: boom")

    # --- data ---
    def get_firmware(self):
        self.calls.append("get_firmware")
        self._maybe_fail("get_firmware")
        from tplinkrouterc6u.common.dataclass import Firmware

        return Firmware("2.20", "Archer C80", "1.2.3 Build 20230101")

    def get_status(self):
        self.calls.append("get_status")
        self._maybe_fail("get_status")
        from tplinkrouterc6u.common.dataclass import Status
        from tplinkrouterc6u.common.package_enum import Connection

        status = Status()
        status._wan_ipv4_addr = _ip("93.184.216.34")
        status._lan_ipv4_addr = _ip("192.168.0.1")
        status._wan_ipv4_gateway = _ip("10.0.0.1")
        status.wan_ipv4_uptime = 3725  # 1 ч 2 мин 5 с
        status.wifi_2g_enable = self._wifi_states[Connection.HOST_2G]
        status.wifi_5g_enable = self._wifi_states[Connection.HOST_5G]
        status.guest_2g_enable = self._wifi_states[Connection.GUEST_2G]
        status.guest_5g_enable = self._wifi_states[Connection.GUEST_5G]
        status.clients_total = 3
        status.wifi_clients_total = 2
        status.wired_total = 1
        status.guest_clients_total = 0
        status.devices = []
        return status

    def get_ipv4_status(self):
        self.calls.append("get_ipv4_status")
        self._maybe_fail("get_ipv4_status")
        from tplinkrouterc6u.common.dataclass import IPv4Status

        ipv4 = IPv4Status()
        ipv4._wan_ipv4_ipaddr = _ip("93.184.216.34")
        ipv4._wan_ipv4_conntype = "PPPoE"
        ipv4._wan_ipv4_gateway = _ip("10.0.0.1")
        ipv4._wan_ipv4_netmask = _ip("255.255.255.255")
        ipv4._wan_ipv4_pridns = _ip("8.8.8.8")
        ipv4._wan_ipv4_snddns = _ip("1.1.1.1")
        ipv4._lan_ipv4_ipaddr = _ip("192.168.0.1")
        ipv4._lan_ipv4_netmask = _ip("255.255.255.0")
        ipv4.lan_ipv4_dhcp_enable = True
        return ipv4

    def get_dhcp_leases(self):
        self.calls.append("get_dhcp_leases")
        self._maybe_fail("get_dhcp_leases")
        from tplinkrouterc6u.common.dataclass import IPv4DHCPLease

        return [
            IPv4DHCPLease(_mac("AA:BB:CC:DD:EE:FF"), _ip("192.168.0.100"), "laptop", "expires 3600"),
        ]

    def get_ipv4_reservations(self):
        self.calls.append("get_ipv4_reservations")
        self._maybe_fail("get_ipv4_reservations")
        from tplinkrouterc6u.common.dataclass import IPv4Reservation

        return [IPv4Reservation(_mac("AA:BB:CC:DD:EE:FF"), _ip("192.168.0.100"), "laptop", True)]

    def set_wifi(self, wifi, enable: bool) -> None:
        self.calls.append("set_wifi")
        self._maybe_fail("set_wifi")
        self.wifi_calls.append((wifi, enable))
        if wifi in self._wifi_states:
            self._wifi_states[wifi] = enable

    def reboot(self) -> None:
        self.calls.append("reboot")
        self._maybe_fail("reboot")
        self.rebooted += 1


def _ip(value: str):
    from ipaddress import IPv4Address

    return IPv4Address(value)


def _mac(value: str):
    from macaddress import EUI48

    return EUI48(value)


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@dataclass
class ManagerHarness:
    """Связка RouterManager + созданный FakeClient для интроспекции."""

    manager: object
    client: FakeClient
    created: list[FakeClient] = field(default_factory=list)

"""Тесты RouterManager: ленивое подключение, кэш сессии, повтор, маппинг ошибок."""

from __future__ import annotations

import pytest
from conftest import FakeClient
from tplinkrouterc6u.common.package_enum import Connection

import router_manager as rm


def make_manager(client: FakeClient, **kwargs) -> rm.RouterManager:
    created: list[FakeClient] = []

    def factory(*args, **_kwargs):
        created.append(client)
        return client

    manager = rm.RouterManager(
        host=client.host,
        password=client.password,
        client_factory=factory,
        logger_=__import__("logging").getLogger("test"),
        **kwargs,
    )
    manager._created = created  # type: ignore[attr-defined]
    return manager


async def test_lazy_authorize_and_status() -> None:
    client = FakeClient()
    manager = make_manager(client)

    assert manager.is_connected is False
    status = await manager.get_status()

    assert client.authorized is True
    assert client.calls[0] == "authorize"
    assert status.wifi_2g_enable is True
    assert manager.is_connected is True


async def test_session_reused_within_ttl() -> None:
    client = FakeClient()
    manager = make_manager(client, session_ttl=600)

    await manager.get_status()
    await manager.get_firmware()

    # authorize вызван один раз, logout — ни разу (сессия жива)
    assert client.calls.count("authorize") == 1
    assert client.logged_out == 0


async def test_session_recreated_when_ttl_zero() -> None:
    client = FakeClient()
    manager = make_manager(client, session_ttl=0)

    await manager.get_status()
    await manager.get_status()

    # каждая операция переподключается
    assert client.calls.count("authorize") == 2


async def test_firmware_parsed() -> None:
    client = FakeClient()
    manager = make_manager(client)

    firmware = await manager.get_firmware()
    assert firmware.model == "Archer C80"
    assert firmware.hardware_version == "2.20"


async def test_authorize_error_maps_to_connection_error() -> None:
    client = FakeClient(authorize_error=rm.AuthorizeError("bad password"))
    manager = make_manager(client)

    with pytest.raises(rm.RouterConnectionError) as exc:
        await manager.get_status()

    assert "отклонил авторизацию" in exc.value.user_message.lower() or "пароль" in exc.value.user_message.lower()
    assert isinstance(exc.value.cause, rm.AuthorizeError)


async def test_network_error_maps_and_retries_once() -> None:
    # Первая попытка get_status падает сетевой ошибкой, вторая проходит.
    client = FakeClient(fail_first_n={"get_status": 1}, fail_with=ConnectionError("no route"))
    manager = make_manager(client, session_ttl=600)

    status = await manager.get_status()

    assert status is not None
    # был повтор: authorize вызван минимум дважды (переподключение)
    assert client.calls.count("authorize") >= 2
    assert client.calls.count("get_status") == 2


async def test_persistent_network_error_raises_connection_error() -> None:
    client = FakeClient(fail_first_n={"get_status": 99}, fail_with=ConnectionError("down"))
    manager = make_manager(client)

    with pytest.raises(rm.RouterConnectionError) as exc:
        await manager.get_status()
    assert "Не удалось подключиться" in exc.value.user_message


async def test_unexpected_response_maps_to_call_error() -> None:
    client = FakeClient(fail_first_n={"get_firmware": 99}, fail_with=KeyError("hardVer"))
    manager = make_manager(client)

    with pytest.raises(rm.RouterCallError):
        await manager.get_firmware()


async def test_set_wifi_and_toggle_confirms() -> None:
    client = FakeClient()
    manager = make_manager(client)
    band = rm.BANDS["5g"]

    state = await manager.toggle_wifi(band, enable=True)

    assert client.wifi_calls == [(Connection.HOST_5G, True)]
    assert state.confirmed is True  # FakeClient вернёт wifi_5g_enable из status
    assert state.enable is True


async def test_set_wifi_guest() -> None:
    client = FakeClient()
    manager = make_manager(client)
    band = rm.BANDS["2g"]

    await manager.toggle_wifi(band, enable=False, guest=True)
    assert client.wifi_calls == [(Connection.GUEST_2G, False)]


async def test_reboot_drops_session() -> None:
    client = FakeClient()
    manager = make_manager(client, session_ttl=600)
    await manager.get_status()
    assert manager.is_connected is True

    await manager.reboot()
    assert client.rebooted == 1
    assert manager.is_connected is False


async def test_close_logs_out() -> None:
    client = FakeClient()
    manager = make_manager(client)
    await manager.get_status()
    await manager.close()
    assert client.logged_out == 1
    assert manager.is_connected is False


async def test_is_supported_true() -> None:
    client = FakeClient()
    manager = make_manager(client)
    assert await manager.is_supported() is True


def test_resolve_band_and_aliases() -> None:
    assert rm.resolve_band("2g") is rm.BANDS["2g"]
    assert rm.resolve_band("2.4") is rm.BANDS["2g"]
    assert rm.resolve_band("5ghz") is rm.BANDS["5g"]
    with pytest.raises(rm.UnknownBand):
        rm.resolve_band("6g")
    with pytest.raises(rm.UnknownBand):
        rm.resolve_band("")


async def test_ping_validates_target() -> None:
    with pytest.raises(rm.InvalidPingTarget):
        await rm.ping_host("not a host!")
    with pytest.raises(rm.InvalidPingTarget):
        await rm.ping_host("")


async def test_ping_localhost() -> None:
    result = await rm.ping_host("127.0.0.1", count=2)
    assert result.target == "127.0.0.1"
    assert result.sent == 2
    # localhost должен отвечать в песочнице
    assert result.ok is True

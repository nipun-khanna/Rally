import asyncio
import socket

from app.browser import egress as egress_mod
from app.browser.egress import PublicEgressProxy


def _answers(*addresses):
    def resolver(host, port, type=0):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]
    return resolver


async def _socks_connect(proxy_url: str, host: str, port: int):
    _, remainder = proxy_url.split("://", 1)
    proxy_host, proxy_port = remainder.rsplit(":", 1)
    reader, writer = await asyncio.open_connection(proxy_host, int(proxy_port))
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    greeting = await reader.readexactly(2)
    host_bytes = host.encode("ascii")
    writer.write(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + port.to_bytes(2, "big"))
    await writer.drain()
    reply = await asyncio.wait_for(reader.readexactly(10), 2)
    return reader, writer, greeting, reply


def test_proxy_rejects_private_destination_and_unsupported_port():
    async def run():
        proxy = PublicEgressProxy(resolver=_answers("10.0.0.8"))
        url = await proxy.start()
        try:
            _, writer, greeting, reply = await _socks_connect(url, "private.test", 443)
            assert greeting == b"\x05\x00"
            assert reply[1] != 0
            writer.close()
        finally:
            await proxy.close()

        proxy = PublicEgressProxy(resolver=_answers("93.184.216.34"))
        url = await proxy.start()
        try:
            _, writer, _, reply = await _socks_connect(url, "example.com", 8080)
            assert reply[1] != 0
            writer.close()
        finally:
            await proxy.close()

    asyncio.run(run())


def test_proxy_rejects_mixed_public_private_dns_answers():
    async def run():
        proxy = PublicEgressProxy(resolver=_answers("93.184.216.34", "127.0.0.1"))
        url = await proxy.start()
        try:
            _, writer, _, reply = await _socks_connect(url, "rebind.test", 443)
            assert reply[1] != 0
            writer.close()
        finally:
            await proxy.close()

    asyncio.run(run())


def test_proxy_reports_connection_refusal_for_validated_public_ip(monkeypatch):
    opened = []
    original = egress_mod.asyncio.open_connection

    async def fake_open(host, port, *args, **kwargs):
        if host == "93.184.216.34":
            opened.append((host, port))
            raise ConnectionRefusedError("refused")
        return await original(host, port, *args, **kwargs)

    monkeypatch.setattr(egress_mod.asyncio, "open_connection", fake_open)

    async def run():
        proxy = PublicEgressProxy(resolver=_answers("93.184.216.34"))
        url = await proxy.start()
        try:
            _, writer, _, reply = await _socks_connect(url, "example.com", 443)
            assert opened == [("93.184.216.34", 443)]
            assert reply[1] != 0
            writer.close()
        finally:
            await proxy.close()

    asyncio.run(run())


def test_proxy_dials_the_validated_ip_not_the_hostname(monkeypatch):
    opened = []
    original = egress_mod.asyncio.open_connection

    async def fake_open(host, port, *args, **kwargs):
        if host == "93.184.216.34":
            opened.append((host, port))
            server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
            local_port = server.sockets[0].getsockname()[1]
            try:
                return await original("127.0.0.1", local_port)
            finally:
                server.close()
                await server.wait_closed()
        return await original(host, port, *args, **kwargs)

    monkeypatch.setattr(egress_mod.asyncio, "open_connection", fake_open)

    async def run():
        proxy = PublicEgressProxy(resolver=_answers("93.184.216.34"))
        url = await proxy.start()
        try:
            _, writer, greeting, reply = await _socks_connect(url, "example.com", 443)
            assert greeting == b"\x05\x00"
            assert reply[1] == 0
            assert opened == [("93.184.216.34", 443)]
            writer.close()
        finally:
            await proxy.close()

    asyncio.run(run())

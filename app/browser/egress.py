"""Loopback SOCKS5 proxy that pins each outbound connection to checked DNS."""

import asyncio
import ipaddress
import socket


class PublicEgressProxy:
    def __init__(self, resolver=socket.getaddrinfo, *, max_connections: int = 32,
                 connect_timeout: float = 10, idle_timeout: float = 60):
        self.resolver = resolver
        self.max_connections = max_connections
        self.connect_timeout = connect_timeout
        self.idle_timeout = idle_timeout
        self._semaphore = asyncio.Semaphore(max_connections)
        self._server = None

    async def start(self) -> str:
        if self._server is None:
            self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0,
                                                      limit=1024)
        port = self._server.sockets[0].getsockname()[1]
        return f"socks5://127.0.0.1:{port}"

    async def close(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, client_reader, client_writer):
        try:
            async with self._semaphore:
                await asyncio.wait_for(self._serve(client_reader, client_writer),
                                       self.idle_timeout)
        except (OSError, asyncio.TimeoutError, ValueError, IndexError):
            pass
        finally:
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except OSError:
                pass

    async def _serve(self, reader, writer):
        version, count = await reader.readexactly(2)
        methods = await reader.readexactly(count)
        if version != 5 or 0 not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            return
        writer.write(b"\x05\x00")
        await writer.drain()
        version, command, reserved, address_type = await reader.readexactly(4)
        if version != 5 or command != 1 or reserved != 0:
            await self._reply(writer, 7)
            return
        if address_type == 1:
            host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        elif address_type == 3:
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode("idna")
        else:
            await self._reply(writer, 8)
            return
        port = int.from_bytes(await reader.readexactly(2), "big")
        if not self._supported_port(port):
            await self._reply(writer, 2)
            return
        try:
            parsed = await self._checked_addresses(host, port)
        except (OSError, ValueError, IndexError, TypeError, asyncio.TimeoutError):
            await self._reply(writer, 2)
            return
        target = str(parsed[0])
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(target, port), self.connect_timeout)
        except (OSError, asyncio.TimeoutError):
            await self._reply(writer, 5)
            return
        await self._reply(writer, 0)
        await asyncio.gather(self._pipe(reader, remote_writer),
                             self._pipe(remote_reader, writer))
        remote_writer.close()
        try:
            await remote_writer.wait_closed()
        except OSError:
            pass

    @staticmethod
    def _supported_port(port: int) -> bool:
        return port in (80, 443)

    async def _checked_addresses(self, host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            addresses = [host]
            ipaddress.ip_address(host)
        except ValueError:
            answers = await asyncio.wait_for(
                asyncio.to_thread(self.resolver, host, port, type=socket.SOCK_STREAM),
                self.connect_timeout)
            addresses = [item[4][0] for item in answers]
        parsed = [ipaddress.ip_address(value.split("%", 1)[0]) for value in addresses]
        if not parsed or any(not item.is_global for item in parsed):
            raise ValueError("Destination is not entirely public")
        return parsed

    async def _reply(self, writer, code):
        writer.write(b"\x05" + bytes([code]) + b"\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

    async def _pipe(self, reader, writer):
        while True:
            block = await asyncio.wait_for(reader.read(65536), self.idle_timeout)
            if not block:
                return
            writer.write(block)
            await writer.drain()

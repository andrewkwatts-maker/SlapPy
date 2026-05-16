from __future__ import annotations
import asyncio
import hashlib
import logging
import socket
import struct
import time
from typing import Callable

logger = logging.getLogger(__name__)

# Public BitTorrent DHT bootstrap nodes (long-lived, maintained by the community)
_DHT_BOOTSTRAP = [
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com",   6881),
    ("dht.transmissionbt.com", 6881),
]

# Public STUN servers for NAT external IP discovery
_STUN_SERVERS = [
    ("stun.l.google.com",       19302),
    ("stun1.l.google.com",      19302),
    ("stun.cloudflare.com",     3478),
]


async def get_external_address(
    local_port: int = 0,
    timeout: float = 3.0,
) -> tuple[str, int] | None:
    """
    Discover external (public) IP and port via STUN.
    Returns (external_ip, external_port) or None on failure.

    Sends a STUN Binding Request and parses the XOR-MAPPED-ADDRESS response.
    Implements a minimal subset of RFC 5389 — Binding Request/Response only.

    Note: UDP hole punching works for most residential NATs (cone NAT).
    Symmetric NATs (common in corporate/enterprise networks) will fail because
    each destination gets a different external port mapping.
    """
    STUN_MAGIC = 0x2112A442
    transaction_id = bytes([0x00] * 12)
    # STUN Binding Request: type=0x0001, length=0, magic, transaction_id
    request = struct.pack("!HHI12s", 0x0001, 0, STUN_MAGIC, transaction_id)

    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("", local_port))

    try:
        for server_host, server_port in _STUN_SERVERS:
            try:
                server_ip = socket.gethostbyname(server_host)
                await loop.sock_sendto(sock, request, (server_ip, server_port))
                data, _ = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024), timeout=timeout
                )
                # Parse STUN response: skip 20-byte header, find XOR-MAPPED-ADDRESS
                pos = 20
                while pos < len(data) - 4:
                    attr_type, attr_len = struct.unpack("!HH", data[pos:pos+4])
                    pos += 4
                    if attr_type in (0x0020, 0x0001):  # XOR-MAPPED-ADDRESS or MAPPED-ADDRESS
                        family = data[pos + 1]
                        if family == 0x01:  # IPv4
                            raw_port, raw_ip = struct.unpack("!HI", data[pos+2:pos+8])
                            if attr_type == 0x0020:
                                port = raw_port ^ (STUN_MAGIC >> 16)
                                ip_int = raw_ip ^ STUN_MAGIC
                            else:
                                port, ip_int = raw_port, raw_ip
                            ip = socket.inet_ntoa(struct.pack("!I", ip_int))
                            return ip, port
                    pos += attr_len + (4 - attr_len % 4) % 4
            except Exception as e:
                logger.debug(f"STUN {server_host} failed: {e}")
                continue
    finally:
        sock.close()
    return None


async def discover_peers_dht(
    room_key: bytes,
    local_addr: tuple[str, int],
    external_addr: tuple[str, int] | None,
    announce_for: float = 30.0,
    on_peer_found: Callable[[str, int], None] | None = None,
) -> list[tuple[str, int]]:
    """
    Use Kademlia DHT to find peers for a given room key.

    Announces our presence at room_key, then looks up who else is there.
    Returns list of (ip, port) for discovered peers.

    Requires: pip install slappyengine[network]
    Falls back gracefully with a warning if kademlia is not installed.
    """
    try:
        from kademlia.network import Server as KademliaServer
    except ImportError:
        logger.warning(
            "kademlia not installed — DHT peer discovery unavailable. "
            "Install with: pip install slappyengine[network]"
        )
        return []

    node = KademliaServer()
    await node.listen(local_addr[1])

    # Bootstrap into the DHT network
    bootstrap_addrs = []
    for host, port in _DHT_BOOTSTRAP:
        try:
            ip = socket.gethostbyname(host)
            bootstrap_addrs.append((ip, port))
        except Exception:
            pass

    if bootstrap_addrs:
        await node.bootstrap(bootstrap_addrs)

    # Announce our presence: store external_addr at room_key
    key_hex = room_key.hex()
    addr_str = (
        f"{external_addr[0]}:{external_addr[1]}"
        if external_addr
        else f"{local_addr[0]}:{local_addr[1]}"
    )
    await node.set(key_hex, addr_str)

    # Look up existing peers
    result = await node.get(key_hex)
    peers = []
    if result:
        for addr_entry in (result if isinstance(result, list) else [result]):
            try:
                ip, port_str = addr_entry.rsplit(":", 1)
                port = int(port_str)
                if (ip, port) != external_addr and (ip, port) != local_addr:
                    peers.append((ip, port))
                    if on_peer_found:
                        on_peer_found(ip, port)
            except Exception:
                pass

    # Keep announcing in background so late joiners can find us
    async def _keepalive():
        end = time.monotonic() + announce_for
        while time.monotonic() < end:
            await asyncio.sleep(10)
            try:
                await node.set(key_hex, addr_str)
            except Exception:
                pass
        node.stop()

    asyncio.ensure_future(_keepalive())
    return peers


async def discover_peers_lan(
    room_code: str,
    port: int = 47823,
    listen_for: float = 2.0,
) -> list[tuple[str, int]]:
    """
    UDP multicast peer discovery for local network play.
    No internet required.

    Broadcasts room_code on LAN multicast group 239.255.42.42 and collects
    responses from other peers on the same subnet.

    The optional zeroconf package (pip install slappyengine[network]) can
    supplement this with mDNS-based discovery, but the raw UDP multicast path
    works without it.
    """
    MCAST_GROUP = "239.255.42.42"
    ANNOUNCE_MSG = f"SlapPyEngine-Room:{room_code}".encode()

    peers = []

    # Send multicast announcement
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        sock.sendto(ANNOUNCE_MSG, (MCAST_GROUP, port))
    except Exception as e:
        logger.debug(f"LAN multicast send failed: {e}")
    finally:
        sock.close()

    # Listen for responses
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(("", port))
    try:
        mreq = struct.pack("4sL", socket.inet_aton(MCAST_GROUP), socket.INADDR_ANY)
        recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        recv_sock.setblocking(False)

        deadline = time.monotonic() + listen_for
        loop = asyncio.get_event_loop()
        while time.monotonic() < deadline:
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(recv_sock, 256),
                    timeout=max(0.01, deadline - time.monotonic())
                )
                if data == ANNOUNCE_MSG and addr[0] not in [p[0] for p in peers]:
                    peers.append(addr)
            except asyncio.TimeoutError:
                break
    except Exception as e:
        logger.debug(f"LAN listen failed: {e}")
    finally:
        recv_sock.close()

    return peers

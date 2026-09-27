"""Protection against server-side request forgery (SSRF).

When URLs come from untrusted users (e.g. the web panel), the crawler must not be
usable to reach the host's own services, the internal network or cloud metadata
endpoints. Every request - including each redirect hop - is checked here first.
"""
import ipaddress
import socket
from urllib.parse import urlparse


class BlockedURL(Exception):
    """Raised when a URL points somewhere the crawler is not allowed to go."""


def is_public_ip(ip):
    ip = ipaddress.ip_address(ip)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class URLGuard:
    def __init__(self, allowed_ports=(80, 443), resolver=socket.getaddrinfo):
        self.allowed_ports = set(allowed_ports) if allowed_ports else None
        self._resolve = resolver

    def check(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise BlockedURL(f"izin verilmeyen şema: {parsed.scheme or '-'}")
        if parsed.username or parsed.password:
            raise BlockedURL("URL içinde kullanıcı adı/parola kullanılamaz")
        host = parsed.hostname
        if not host:
            raise BlockedURL("adres bir sunucu adı içermiyor")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise BlockedURL("geçersiz port") from exc
        if self.allowed_ports is not None and port not in self.allowed_ports:
            raise BlockedURL(f"izin verilmeyen port: {port}")
        try:
            infos = self._resolve(host, port, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError) as exc:
            raise BlockedURL(f"sunucu adı çözülemedi: {host}") from exc
        addresses = {info[4][0] for info in infos}
        if not addresses:
            raise BlockedURL(f"sunucu adı çözülemedi: {host}")
        for address in addresses:
            if not is_public_ip(address.split("%", 1)[0]):
                raise BlockedURL(f"iç ağ / özel adres engellendi: {host} → {address}")

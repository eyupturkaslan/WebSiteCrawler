from urllib.parse import urljoin, urlparse, urlunparse

SKIPPED_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "ftp:")
DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url):
    """Return a canonical form of url: lowercase scheme/host, no default port, no fragment."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if parsed.port and parsed.port != DEFAULT_PORTS.get(scheme):
        host = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((scheme, host, path, parsed.params, parsed.query, ""))


def resolve_link(base_url, href):
    """Turn an href found on base_url into an absolute, normalized http(s) URL, or None."""
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith(SKIPPED_SCHEMES):
        return None
    absolute = urljoin(base_url, href)
    if urlparse(absolute).scheme not in DEFAULT_PORTS:
        return None
    return normalize_url(absolute)


def site_key(url):
    """Host used to decide whether two URLs belong to the same site (ignores a leading www.)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parsed.port and parsed.port != DEFAULT_PORTS.get(parsed.scheme):
        host = f"{host}:{parsed.port}"
    return host


def same_site(url, other):
    return site_key(url) == site_key(other)

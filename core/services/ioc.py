"""Deterministic, bounded IOC extraction and normalization."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class IOC:
    type: str
    value: str
    original: str


_PATTERNS = {
    "URL": re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE),
    "EMAIL": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "HASH": re.compile(r"\b(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}|[A-Fa-f0-9]{96}|[A-Fa-f0-9]{128})\b"),
    "CVE": re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE),
    "USERNAME": re.compile(r"(?<![\w])@([A-Za-z0-9_]{3,32})\b"),
    "IP": re.compile(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f:]{1,4}(?![\w:])"),
    "DOMAIN": re.compile(r"(?<![@\w.-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}\b", re.IGNORECASE),
}
_MAX_TEXT = 64 * 1024
_MAX_RESULTS = 256


def extract(text: str, *, max_results: int = _MAX_RESULTS) -> list[IOC]:
    """Extract deterministic indicators from bounded text with stable ordering."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    text = text[:_MAX_TEXT]
    found: dict[tuple[str, str], IOC] = {}
    for kind, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            original = match.group(0)
            value = normalize(kind, original)
            if value is None:
                continue
            found.setdefault((kind, value), IOC(kind, value, original))
            if len(found) >= max(1, min(int(max_results), _MAX_RESULTS)):
                break
    return sorted(found.values(), key=lambda item: (item.type, item.value))[:_MAX_RESULTS]


def normalize(kind: str, value: str) -> str | None:
    kind = kind.upper()
    value = value.strip().strip(".,;:!?)]}")
    if not value:
        return None
    if kind == "IP":
        try:
            return ipaddress.ip_address(value).compressed
        except ValueError:
            return None
    if kind == "EMAIL":
        return value.casefold()
    if kind == "DOMAIN":
        return value.rstrip(".").casefold()
    if kind == "USERNAME":
        return value.lstrip("@").casefold()
    if kind == "CVE":
        return value.upper()
    if kind == "HASH":
        length = len(value)
        algorithm = {32: "MD5", 40: "SHA1", 64: "SHA256", 96: "SHA384", 128: "SHA512"}.get(length)
        return f"{algorithm}:{value.lower()}" if algorithm else value.lower()
    if kind == "URL":
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.casefold(), parsed.path or "/", parsed.query, ""))
    return value

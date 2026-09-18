"""Bounded defensive URL, IDN and public reputation analysis.

This service never performs active scanning, credential discovery or restriction
circumvention. Reputation adapters query public defensive services only and
return minimized metadata.
"""

from __future__ import annotations

import ipaddress
import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit


_MAX_URL = 2048
_MAX_DOMAIN = 253
_MAX_REPUTATION_BYTES = 256 * 1024
_HASH_RE = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


@dataclass(frozen=True, slots=True)
class IDNAnalysis:
    input: str
    ascii: str
    unicode: str
    scripts: tuple[str, ...]
    mixed_script: bool
    punycode: bool
    visual_similarity: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    target: str
    score: int
    level: str
    signals: tuple[str, ...]
    idn: IDNAnalysis | None = None


class SecurityIntelService:
    """Own deterministic defensive security analysis and public reputation adapters."""

    def __init__(self, http, public_intel=None):
        self.http = http
        self.public_intel = public_intel

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @staticmethod
    def _domain_from_target(target: str) -> str:
        value = target.strip()
        if not value:
            raise ValueError("A URL, domain or hash is required.")
        if len(value) > _MAX_URL:
            raise ValueError("Target exceeds the 2048-character limit.")
        if "://" not in value:
            value = "https://" + value
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        if not host or len(host) > _MAX_DOMAIN:
            raise ValueError("Target does not contain a valid bounded hostname.")
        return host

    @staticmethod
    def analyze_idn(target: str) -> IDNAnalysis:
        host = SecurityIntelService._domain_from_target(target)
        try:
            ascii_host = host.encode("idna").decode("ascii")
            unicode_host = ascii_host.encode("ascii").decode("idna")
        except UnicodeError as exc:
            raise ValueError("Hostname contains invalid IDN data.") from exc

        scripts: set[str] = set()
        for char in unicode_host:
            if not char.isalpha():
                continue
            name = unicodedata.name(char, "")
            script = next(
                (
                    item
                    for item in (
                        "LATIN", "CYRILLIC", "GREEK", "HEBREW", "ARABIC",
                        "DEVANAGARI", "ARMENIAN", "GEORGIAN", "HIRAGANA",
                        "KATAKANA", "HANGUL", "CJK",
                    )
                    if item in name
                ),
                "OTHER",
            )
            scripts.add(script)

        labels = unicode_host.split(".")
        visual_similarity: list[str] = []
        confusables = {
            "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",
            "у": "y", "і": "i", "ј": "j", "ο": "o", "ρ": "p",
        }
        skeleton = "".join(confusables.get(char, char) for char in unicode_host)
        if skeleton != unicode_host:
            visual_similarity.append("Unicode confusable characters detected")
        if any(label.startswith("xn--") for label in labels):
            visual_similarity.append("Punycode label present")

        return IDNAnalysis(
            input=host,
            ascii=ascii_host,
            unicode=unicode_host,
            scripts=tuple(sorted(scripts)),
            mixed_script=len(scripts) > 1,
            punycode=any(label.startswith("xn--") for label in labels),
            visual_similarity=tuple(visual_similarity),
        )


    @staticmethod
    def extract_urls(text: str) -> list[str]:
        if not text:
            return []
        urls = re.findall(r"https?://[^\\s<>()[\\]]+", text[:4000], flags=re.IGNORECASE)
        return list(dict.fromkeys(url.rstrip(".,;:") for url in urls))[:3]

    async def assess_text(self, text: str) -> dict:
        urls = self.extract_urls(text)
        assessments = []
        for url in urls:
            assessments.append(await self.assess_url(url))
        return {"urls": urls, "assessments": tuple(assessments)}

    async def assess_url(self, target: str, *, follow_redirects: bool = True) -> RiskAssessment:
        value = target.strip()
        if not value:
            raise ValueError("A URL is required.")
        if len(value) > _MAX_URL:
            raise ValueError("URL exceeds the 2048-character limit.")
        if "://" not in value:
            value = "https://" + value
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only http:// and https:// URLs are supported.")

        idn = self.analyze_idn(value)
        signals: list[str] = []
        score = 0

        if parsed.scheme.lower() == "http":
            score += 15
            signals.append("Unencrypted HTTP scheme")
        if parsed.username or parsed.password:
            score += 25
            signals.append("Userinfo embedded in URL")
        try:
            ipaddress.ip_address(parsed.hostname)
            score += 15
            signals.append("URL host is a literal IP address")
        except ValueError:
            pass
        if idn.punycode:
            score += 15
            signals.append("Punycode/IDN host")
        if idn.mixed_script:
            score += 25
            signals.append("Mixed Unicode scripts in hostname")
        if idn.visual_similarity:
            score += 15
            signals.extend(idn.visual_similarity)
        if len(parsed.hostname) > 100:
            score += 10
            signals.append("Unusually long hostname")
        if len(parsed.path) > 512:
            score += 10
            signals.append("Unusually long URL path")
        if parsed.query and len(parsed.query) > 1024:
            score += 10
            signals.append("Unusually large query string")

        redirect_hops: list[str] = []
        if follow_redirects and self.public_intel is not None:
            try:
                result = await self.public_intel.link_intel(value)
                rows = result.get("rows", []) if isinstance(result, dict) else []
                for row in rows:
                    if isinstance(row, str) and row.startswith("  "):
                        redirect_hops.append(row.strip())
                if len(redirect_hops) >= 3:
                    score += 10
                    signals.append(f"Long redirect chain ({len(redirect_hops)} observed hops)")
            except Exception:
                signals.append("Redirect analysis unavailable")

        score = min(100, score)
        level = "LOW" if score < 30 else "MEDIUM" if score < 60 else "HIGH"
        if not signals:
            signals.append("No local heuristic risk signals detected")
        return RiskAssessment(value, score, level, tuple(dict.fromkeys(signals)), idn)

    async def reputation_urlhaus(self, target: str) -> dict:
        value = target.strip()
        if len(value) > _MAX_URL:
            raise ValueError("URL exceeds the 2048-character limit.")
        response = await self.http.post(
            "https://urlhaus-api.abuse.ch/v1/url/",
            data={"url": value},
            allow_redirects=False,
            response_limit=_MAX_REPUTATION_BYTES,
            retries=1,
        )
        if response.status not in {200, 404}:
            return {"provider": "URLhaus", "status": "UNKNOWN", "detail": f"HTTP {response.status}"}
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            return {"provider": "URLhaus", "status": "UNKNOWN", "detail": "Invalid provider response"}
        query_status = str(payload.get("query_status", "unknown")).upper()
        if query_status == "OK":
            return {
                "provider": "URLhaus",
                "status": "FOUND",
                "url_status": str(payload.get("url_status", "unknown")),
                "threat": str(payload.get("threat", "unknown")),
                "date_added": str(payload.get("date_added", ""))[:40],
            }
        if query_status in {"NO_RESULTS", "NOT_FOUND"}:
            return {"provider": "URLhaus", "status": "NOT_FOUND"}
        return {"provider": "URLhaus", "status": "UNKNOWN", "detail": query_status}

    async def reputation_hash(self, digest: str) -> dict:
        value = digest.strip().lower()
        if not _HASH_RE.fullmatch(value):
            raise ValueError("Hash must be a bounded MD5, SHA-1 or SHA-256 hexadecimal digest.")
        response = await self.http.post(
            "https://mb-api.abuse.ch/api/v1/",
            data={"query": "get_info", "hash": value},
            allow_redirects=False,
            response_limit=_MAX_REPUTATION_BYTES,
            retries=1,
        )
        if response.status != 200:
            return {"provider": "MalwareBazaar", "status": "UNKNOWN", "detail": f"HTTP {response.status}"}
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            return {"provider": "MalwareBazaar", "status": "UNKNOWN", "detail": "Invalid provider response"}
        query_status = str(payload.get("query_status", "unknown")).upper()
        if query_status == "OK":
            rows = payload.get("data") or []
            first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
            return {
                "provider": "MalwareBazaar",
                "status": "FOUND",
                "signature": str(first.get("signature", ""))[:120],
                "first_seen": str(first.get("first_seen", ""))[:40],
                "file_type": str(first.get("file_type", ""))[:80],
            }
        if query_status in {"NO_RESULTS", "NOT_FOUND"}:
            return {"provider": "MalwareBazaar", "status": "NOT_FOUND"}
        return {"provider": "MalwareBazaar", "status": "UNKNOWN", "detail": query_status}

    async def inspect(self, target: str) -> dict:
        value = target.strip()
        if not value:
            raise ValueError("A URL, domain or hash is required.")
        if _HASH_RE.fullmatch(value):
            reputation = await self.reputation_hash(value)
            return {"kind": "hash", "target": value.lower(), "reputation": reputation}

        url_like = "://" in value or "/" in value
        if url_like:
            assessment = await self.assess_url(value)
            reputation = await self.reputation_urlhaus(value)
            return {"kind": "url", "target": value, "assessment": assessment, "reputation": reputation}

        idn = self.analyze_idn(value)
        return {"kind": "domain", "target": value, "idn": idn}

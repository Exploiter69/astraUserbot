"""Bounded public-source intelligence adapters for Phase 8.

The service records only normalized observations and provenance in IntelGraph. It
never turns a username/domain correlation into an identity assertion.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import socket
import ssl
import time
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from core.services.http import HttpService
from core.services.intelgraph import IntelGraph
from core.services.telegram import TelegramFacade

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
_MAX_TEXT = 12_000
_MAX_RESULTS = 20
_MAX_REDIRECTS = 5


class PublicIntelService:
    """Collect bounded public observations through existing local services."""

    def __init__(self, graph: IntelGraph, http: HttpService, telegram: TelegramFacade) -> None:
        self.graph = graph
        self.http = http
        self.telegram = telegram

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def _source(self, source_id: str, family: str, provider: str, source_type: str, uri: str | None = None) -> None:
        await self.graph.add_source(
            source_id=source_id,
            source_family=family,
            provider=provider,
            source_type=source_type,
            uri=uri,
            lineage_class="PUBLIC_OBSERVED",
            lineage_confidence=1.0,
            metadata={"bounded": True, "public_only": True},
        )

    @staticmethod
    def _clean_username(value: str) -> str:
        value = value.strip().lstrip("@").strip()
        if not _USERNAME_RE.fullmatch(value):
            raise ValueError("Username must contain 3-32 ASCII letters, digits or underscores.")
        return value.lower()

    @staticmethod
    def _clean_domain(value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if "://" in value:
            value = urlsplit(value).hostname or ""
        if not _DOMAIN_RE.fullmatch(value):
            raise ValueError("Invalid domain.")
        return value

    @staticmethod
    def _clean_url(value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("URL must use http:// or https:// and include a host.")
        host = parsed.hostname.lower()
        netloc = host
        if parsed.port is not None:
            netloc = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))

    async def telegram_intel(self, target: str) -> dict:
        username = self._clean_username(target)
        source_id = f"telegram:intel:{username}"
        await self._source(source_id, "telegram_public", "Telegram", "public_profile", f"https://t.me/{username}")
        entity = await self.telegram.get_entity(f"@{username}")
        entity_type = type(entity).__name__
        canonical = getattr(entity, "username", None) or username
        username_id = await self.graph.add_entity(entity_type="USERNAME", canonical_value=str(canonical).lower(), display_value=f"@{canonical}")
        observation = await self.graph.add_observation(
            entity_id=username_id,
            source_id=source_id,
            source_family="telegram_public",
            matched_field="username",
            match_type="exact",
            confidence=1.0,
            provenance={"observable": True, "entity_type": entity_type},
        )
        rows = [f"Username: @{canonical}", f"Entity type: {entity_type}", f"Telegram ID: {getattr(entity, 'id', 'unknown')}"]
        title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
        if title:
            rows.append(f"Name/title: {str(title)[:160]}")
        about = getattr(entity, "about", None)
        if about:
            about = str(about)[:1000]
            rows.append(f"Bio/about: {about}")
            for url in self._extract_urls(about):
                url_id = await self.graph.add_entity(entity_type="URL", canonical_value=url)
                await self.graph.add_observation(entity_id=url_id, source_id=source_id, source_family="telegram_public", matched_field="bio_url", match_type="exact", confidence=1.0, provenance={"record": "public_bio"})
                await self.graph.add_relationship(from_entity_id=username_id, relationship_type="LINKS_TO", to_entity_id=url_id, evidence_state="OBSERVED", confidence=1.0, observation_id=observation)
        return {"target": username, "rows": rows, "observation_id": observation}

    async def username_pivot(self, target: str) -> dict:
        username = self._clean_username(target)
        source_id = f"username:pivot:{username}"
        await self._source(source_id, "public_profile", "Astra", "username_pivot")
        username_id = await self.graph.add_entity(entity_type="USERNAME", canonical_value=username, display_value=f"@{username}")
        probes = [
            ("github", f"https://api.github.com/users/{username}", "https://github.com/{username}"),
            ("gitlab", f"https://gitlab.com/api/v4/users?username={username}", "https://gitlab.com/{username}"),
            ("reddit", f"https://www.reddit.com/user/{username}/about.json", "https://www.reddit.com/user/{username}/"),
        ]
        findings = []
        for provider, api_url, profile_template in probes:
            try:
                headers = {"User-Agent": "AstraUserbot/2.x public-intel"}
                response = await self.http.get(api_url, headers=headers, allow_redirects=True, response_limit=256 * 1024)
                if response.status != 200:
                    continue
                profile_url = profile_template.format(username=username)
                profile_id = await self.graph.add_entity(entity_type="PUBLIC_PROFILE", canonical_value=f"{provider}:{username}", display_value=profile_url)
                obs = await self.graph.add_observation(entity_id=profile_id, source_id=source_id, source_family="public_profile", matched_field="username", match_type="exact", confidence=0.9, provenance={"provider": provider, "status": response.status, "uri": profile_url})
                await self.graph.add_relationship(from_entity_id=username_id, relationship_type="LINKS_TO", to_entity_id=profile_id, evidence_state="OBSERVED", confidence=0.9, observation_id=obs)
                findings.append(f"{provider}: public profile observed")
            except Exception:
                findings.append(f"{provider}: unavailable")
        return {"target": username, "rows": [f"Username: @{username}", "", *findings] or [f"No public profiles observed for @{username}"], "findings": findings}

    async def domain_intel(self, target: str, *, include_ct: bool = False) -> dict:
        domain = self._clean_domain(target)
        source_id = f"domain:intel:{domain}"
        await self._source(source_id, "domain_public", "Astra", "domain_intelligence")
        domain_id = await self.graph.add_entity(entity_type="DOMAIN", canonical_value=domain)
        rows = [f"Domain: {domain}"]

        addresses = await self._resolve(domain)
        for address in addresses[:8]:
            ip_id = await self.graph.add_entity(entity_type="IP", canonical_value=address)
            obs = await self.graph.add_observation(entity_id=ip_id, source_id=source_id, source_family="domain_public", matched_field="dns", match_type="exact", confidence=1.0, provenance={"record": "getaddrinfo"})
            await self.graph.add_relationship(from_entity_id=domain_id, relationship_type="RESOLVES_TO", to_entity_id=ip_id, evidence_state="OBSERVED", confidence=1.0, observation_id=obs)
        rows.append(f"DNS addresses: {', '.join(addresses[:8]) if addresses else 'none observed'}")

        try:
            rdap = await self.http.get(f"https://rdap.org/domain/{domain}", response_limit=512 * 1024)
            if rdap.status == 200:
                data = json.loads(rdap.text)
                nameservers = [item.get("ldhName") for item in data.get("nameservers", []) if item.get("ldhName")]
                registrar = self._rdap_registrar(data)
                rows.append(f"RDAP: available{f' · registrar={registrar}' if registrar else ''}")
                if nameservers:
                    rows.append(f"Nameservers: {', '.join(nameservers[:8])}")
        except Exception:
            rows.append("RDAP: unavailable")

        http_meta = await self._http_metadata(domain)
        rows.extend(http_meta)
        tls = await self._tls_metadata(domain)
        rows.extend(tls)

        if include_ct:
            ct = await self.certificate_transparency(domain)
            rows.extend(ct["rows"][1:])
        return {"target": domain, "rows": rows}

    async def certificate_transparency(self, target: str) -> dict:
        domain = self._clean_domain(target)
        source_id = f"ct:{domain}"
        await self._source(source_id, "certificate_transparency", "crt.sh", "ct_json", f"https://crt.sh/?q=%25.{domain}&output=json")
        domain_id = await self.graph.add_entity(entity_type="DOMAIN", canonical_value=domain)
        rows = [f"Domain: {domain}"]
        try:
            response = await self.http.get(f"https://crt.sh/?q=%25.{domain}&output=json", response_limit=2 * 1024 * 1024)
            if response.status != 200:
                return {"target": domain, "rows": [*rows, f"CT: HTTP {response.status}"]}
            data = json.loads(response.text)
            names: set[str] = set()
            for item in data[:500]:
                for name in str(item.get("name_value", "")).splitlines():
                    name = name.strip().lower().lstrip("*.")
                    if name == domain or name.endswith("." + domain):
                        names.add(name)
            for name in sorted(names)[:100]:
                sub_id = await self.graph.add_entity(entity_type="DOMAIN", canonical_value=name)
                obs = await self.graph.add_observation(entity_id=sub_id, source_id=source_id, source_family="certificate_transparency", matched_field="name_value", match_type="exact", confidence=1.0, provenance={"source": "crt.sh"})
                await self.graph.add_relationship(from_entity_id=domain_id, relationship_type="MENTIONS", to_entity_id=sub_id, evidence_state="OBSERVED", confidence=1.0, observation_id=obs)
            rows.append(f"CT names: {len(names)}")
            rows.extend(f"  · {name}" for name in sorted(names)[:12])
        except Exception:
            rows.append("CT: unavailable")
        return {"target": domain, "rows": rows}

    async def link_intel(self, target: str) -> dict:
        url = self._clean_url(target)
        source_id = f"link:intel:{hashlib.sha256(url.encode()).hexdigest()[:20]}"
        await self._source(source_id, "link_public", "Astra", "redirect_graph", url)
        root_id = await self.graph.add_entity(entity_type="URL", canonical_value=url)
        rows = [f"URL: {url}"]
        current = url
        current_id = root_id
        seen = {current}
        hops = []
        for _ in range(_MAX_REDIRECTS):
            response = await self.http.head(current, allow_redirects=False, response_limit=16 * 1024)
            location = response.headers.get("Location")
            if response.status not in {301, 302, 303, 307, 308} or not location:
                if response.status == 405:
                    response = await self.http.get(current, allow_redirects=False, response_limit=16 * 1024)
                    location = response.headers.get("Location")
                if response.status not in {301, 302, 303, 307, 308} or not location:
                    break
            nxt = self._clean_url(urljoin(current, location))
            if nxt in seen:
                rows.append("Redirect loop detected; stopped.")
                break
            seen.add(nxt)
            hops.append(nxt)
            child_id = await self.graph.add_entity(entity_type="URL", canonical_value=nxt)
            obs = await self.graph.add_observation(entity_id=child_id, source_id=source_id, source_family="link_public", matched_field="location", match_type="exact", confidence=1.0, provenance={"from": current, "status": response.status})
            await self.graph.add_relationship(from_entity_id=current_id, relationship_type="LINKS_TO", to_entity_id=child_id, evidence_state="OBSERVED", confidence=1.0, observation_id=obs)
            current = nxt
            current_id = child_id
        rows.append(f"Redirect hops: {len(hops)}")
        rows.extend(f"  {index + 1}. {value}" for index, value in enumerate(hops[:_MAX_RESULTS]))
        final = urlsplit(current).hostname
        if final:
            domain_id = await self.graph.add_entity(entity_type="DOMAIN", canonical_value=final)
            obs = await self.graph.add_observation(entity_id=domain_id, source_id=source_id, source_family="link_public", matched_field="final_host", match_type="exact", confidence=1.0, provenance={"final_url": current})
            await self.graph.add_relationship(from_entity_id=current_id, relationship_type="LINKS_TO", to_entity_id=domain_id, evidence_state="OBSERVED", confidence=1.0, observation_id=obs)
        return {"target": url, "rows": rows}

    async def git_intel(self, target: str) -> dict:
        username = self._clean_username(target)
        source_id = f"git:intel:{username}"
        await self._source(source_id, "public_code", "GitHub/GitLab", "public_profile_search")
        username_id = await self.graph.add_entity(entity_type="USERNAME", canonical_value=username, display_value=f"@{username}")
        rows = [f"Username: @{username}"]
        github = await self._github_public(username)
        gitlab = await self._gitlab_public(username)
        for provider, projects in (("GitHub", github), ("GitLab", gitlab)):
            rows.append(f"{provider} public projects: {len(projects)}")
            for project in projects[:8]:
                url = project.get("html_url") or project.get("web_url")
                if not url:
                    continue
                repo_id = await self.graph.add_entity(entity_type="REPOSITORY", canonical_value=url, display_value=project.get("name") or url)
                obs = await self.graph.add_observation(entity_id=repo_id, source_id=source_id, source_family="public_code", matched_field="public_repository", match_type="exact", confidence=0.95, provenance={"provider": provider, "url": url})
                await self.graph.add_relationship(from_entity_id=username_id, relationship_type="LINKS_TO", to_entity_id=repo_id, evidence_state="OBSERVED", confidence=0.95, observation_id=obs)
                rows.append(f"  · {provider}: {project.get('name') or url}")
        return {"target": username, "rows": rows}

    async def _github_public(self, username: str) -> list[dict]:
        response = await self.http.get(f"https://api.github.com/users/{username}/repos", headers={"Accept": "application/vnd.github+json", "User-Agent": "AstraUserbot/2.x public-intel"}, params={"per_page": str(_MAX_RESULTS), "type": "owner"}, response_limit=512 * 1024)
        if response.status != 200:
            return []
        data = json.loads(response.text)
        return [item for item in data if isinstance(item, dict)]

    async def _gitlab_public(self, username: str) -> list[dict]:
        response = await self.http.get("https://gitlab.com/api/v4/users", params={"username": username}, headers={"User-Agent": "AstraUserbot/2.x public-intel"}, response_limit=256 * 1024)
        if response.status != 200:
            return []
        users = json.loads(response.text)
        if not users:
            return []
        user_id = users[0].get("id")
        if not user_id:
            return []
        response = await self.http.get(f"https://gitlab.com/api/v4/users/{user_id}/projects", params={"per_page": str(_MAX_RESULTS), "simple": "true"}, headers={"User-Agent": "AstraUserbot/2.x public-intel"}, response_limit=512 * 1024)
        if response.status != 200:
            return []
        data = json.loads(response.text)
        return [item for item in data if isinstance(item, dict)]

    async def _resolve(self, domain: str) -> list[str]:
        try:
            results = await asyncio.get_running_loop().run_in_executor(None, lambda: socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM))
            return sorted({str(item[4][0]) for item in results if item[4]})
        except OSError:
            return []

    async def _http_metadata(self, domain: str) -> list[str]:
        try:
            response = await self.http.head(f"https://{domain}", allow_redirects=True, response_limit=16 * 1024)
            return [f"HTTP: {response.status}", f"Final URL: {response.url}", f"Server: {response.headers.get('Server', '—')}", f"Content-Type: {response.headers.get('Content-Type', '—')}"]
        except Exception:
            return ["HTTP: unavailable"]

    async def _tls_metadata(self, domain: str) -> list[str]:
        def probe() -> tuple[str | None, str | None]:
            context = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=8) as raw:
                with context.wrap_socket(raw, server_hostname=domain) as sock:
                    cert = sock.getpeercert()
                    subject = cert.get("subject", ())
                    issuer = cert.get("issuer", ())

                    def flatten(parts: Iterable[tuple[tuple[str, str], ...]]) -> str | None:
                        values = [value for group in parts for key, value in group if key in {"commonName", "organizationName"}]
                        return values[0] if values else None

                    return flatten(subject), flatten(issuer)

        try:
            subject, issuer = await asyncio.to_thread(probe)
            return [f"TLS subject: {subject or '—'}", f"TLS issuer: {issuer or '—'}"]
        except Exception:
            return ["TLS: unavailable"]

    @staticmethod
    def _rdap_registrar(data: dict) -> str | None:
        for entity in data.get("entities", []):
            roles = entity.get("roles") or []
            if "registrar" not in roles:
                continue
            for item in entity.get("vcardArray", [None, []])[1]:
                if isinstance(item, list) and len(item) >= 4 and item[0] in {"fn", "org"}:
                    return str(item[3])[:120]
        return None

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        urls = re.findall(r"https?://[^\s<>\]\[)]+", text[:_MAX_TEXT])
        return list(dict.fromkeys(url.rstrip(".,;:") for url in urls))[:_MAX_RESULTS]

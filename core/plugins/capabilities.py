"""Phase 4 capability vocabulary, grant resolution, identity, and audit contracts.

These checks govern supported APIs; they are not a Python sandbox.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import time
from typing import Any, Iterator

from core.services.storage import StorageService

logger = logging.getLogger("astra.capabilities")

CAPABILITIES = frozenset(
    {
        "telegram.read",
        "telegram.write",
        "network.external",
        "fs.read",
        "fs.write",
        "subprocess",
        "jobs.enqueue",
        "ai.remote",
        "ai.local",
        "vault.read",
        "vault.write",
    }
)
POLICY_MODES = frozenset({"ENFORCED", "LEGACY_UNDECLARED"})


def validate_capabilities(values: Any) -> tuple[str, ...]:
    """Validate known capability identifiers and reject duplicates."""
    if isinstance(values, (str, bytes)) or values is None:
        raise ValueError("Capabilities must be an iterable of unique names")
    try:
        result = tuple(values)
    except TypeError as exc:
        raise ValueError("Capabilities must be an iterable of unique names") from exc
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError("Capability names must be non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError("Duplicate capability names are not allowed")
    unknown = set(result) - CAPABILITIES
    if unknown:
        raise ValueError(f"Unknown capabilities: {', '.join(sorted(unknown))}")
    return result


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    kind: str
    name: str


_current_identity: ContextVar[ExecutionIdentity | None] = ContextVar(
    "astra_execution_identity", default=None
)


def current_identity() -> ExecutionIdentity | None:
    return _current_identity.get()


@contextmanager
def identity_context(identity: ExecutionIdentity) -> Iterator[None]:
    token = _current_identity.set(identity)
    try:
        yield
    finally:
        _current_identity.reset(token)


@contextmanager
def trusted_core_context(component: str) -> Iterator[None]:
    """Mark framework-owned work explicitly; never use around plugin callbacks."""
    if not component or not isinstance(component, str):
        raise ValueError("Trusted-core component name is required")
    with identity_context(ExecutionIdentity("trusted_core", component)):
        yield


@contextmanager
def plugin_identity_context(plugin: str) -> Iterator[None]:
    """Bind a callback to its plugin identity without granting core authority."""
    if not plugin or not isinstance(plugin, str):
        raise ValueError("Plugin identity is required")
    with identity_context(ExecutionIdentity("plugin", plugin)):
        yield


class CapabilityDeniedError(PermissionError):
    """Raised when an enforced plugin lacks a required capability."""

    code = "CAPABILITY_DENIED"

    def __init__(
        self,
        plugin: str,
        capability: str,
        operation: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self.plugin = plugin
        self.capability = capability
        self.operation = operation
        self.correlation_id = correlation_id
        super().__init__(
            f"Capability denied: plugin={plugin} operation={operation} "
            f"required={capability}"
        )


class CapabilityPolicyError(RuntimeError):
    """Raised when a plugin's effective capability policy cannot be resolved."""


class CapabilityGrantStore:
    """Persist owner-approved grants using the canonical platform storage."""

    def __init__(self, storage: StorageService) -> None:
        self.storage = storage
        self._change_callbacks: list[Any] = []

    def add_change_callback(self, callback: Any) -> None:
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)

    async def get_grants(self, plugin: str) -> frozenset[str]:
        rows = await self.storage.fetchall(
            "SELECT capability FROM plugin_capability_grants WHERE plugin_name=? "
            "ORDER BY capability",
            (plugin,),
        )
        try:
            return frozenset(validate_capabilities(row["capability"] for row in rows))
        except ValueError as exc:
            raise CapabilityPolicyError(
                f"Invalid stored capability grant for plugin {plugin}"
            ) from exc

    async def replace_grants(
        self,
        plugin: str,
        capabilities: Any,
        *,
        granted_by: str,
    ) -> None:
        if not plugin or not isinstance(plugin, str):
            raise ValueError("Plugin name is required")
        if not granted_by or not isinstance(granted_by, str):
            raise ValueError("Granting owner identity is required")
        identity = current_identity()
        if identity is None or identity.kind != "trusted_core":
            raise PermissionError("Capability grants may only be mutated by authorized core code")
        validated = validate_capabilities(capabilities)
        statements = [
            (
                "DELETE FROM plugin_capability_grants WHERE plugin_name=?",
                (plugin,),
            )
        ]
        now = time()
        statements.extend(
            (
                "INSERT INTO plugin_capability_grants"
                "(plugin_name, capability, granted_by, granted_at) VALUES (?,?,?,?)",
                (plugin, capability, granted_by, now),
            )
            for capability in validated
        )
        await self.storage.transaction(statements)
        for callback in tuple(self._change_callbacks):
            result = callback(plugin, frozenset(validated))
            if hasattr(result, "__await__"):
                await result


@dataclass(frozen=True, slots=True)
class _PluginPolicy:
    declared: frozenset[str]
    approved: frozenset[str]
    effective: frozenset[str]
    mode: str


class CapabilityRuntime:
    """Resolve policies once per load and authorize without storage hot-path reads."""

    def __init__(
        self,
        grants: CapabilityGrantStore,
        storage: StorageService,
    ) -> None:
        self.grants = grants
        self.storage = storage
        self._cache: dict[str, _PluginPolicy] = {}
        self.grants.add_change_callback(self.invalidate)

    async def load_plugin(
        self,
        plugin: str,
        *,
        declared: Any,
        mode: str = "ENFORCED",
    ) -> frozenset[str]:
        if mode not in POLICY_MODES:
            raise CapabilityPolicyError(f"Unknown plugin policy mode: {mode}")
        try:
            declared_set = frozenset(validate_capabilities(declared))
            approved = await self.grants.get_grants(plugin)
        except ValueError as exc:
            raise CapabilityPolicyError(
                f"Invalid capability declaration for plugin {plugin}"
            ) from exc
        if mode == "LEGACY_UNDECLARED" and declared_set:
            raise CapabilityPolicyError(
                f"Legacy policy requires an undeclared plugin: {plugin}"
            )
        effective = (
            frozenset(CAPABILITIES)
            if mode == "LEGACY_UNDECLARED"
            else declared_set & approved
        )
        self._cache[plugin] = _PluginPolicy(
            declared=declared_set,
            approved=approved,
            effective=effective,
            mode=mode,
        )
        return effective

    def invalidate(
        self,
        plugin: str | None = None,
        approved: frozenset[str] | None = None,
    ) -> None:
        """Invalidate on reload, or atomically replace grants after mutation.

        Grant mutations pass the already-committed grant set so the next call
        never reads storage and never sees a stale revoked grant.
        """
        if plugin is None:
            self._cache.clear()
            return
        previous = self._cache.get(plugin)
        if approved is not None and previous is not None:
            effective = (
                frozenset(CAPABILITIES)
                if previous.mode == "LEGACY_UNDECLARED"
                else previous.declared & approved
            )
            self._cache[plugin] = _PluginPolicy(
                declared=previous.declared,
                approved=approved,
                effective=effective,
                mode=previous.mode,
            )
        else:
            self._cache.pop(plugin, None)

    async def authorize(
        self,
        plugin: str,
        capability: str,
        operation: str,
        *,
        call_site: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Audit and authorize a supported call before its side effect.

        Details are intentionally not persisted: callers may supply sensitive
        payloads, so the audit event uses only bounded policy metadata.
        """
        if capability not in CAPABILITIES:
            raise CapabilityPolicyError(f"Unknown capability: {capability}")
        identity = current_identity()
        correlation_id = uuid.uuid4().hex[:12]
        if (
            identity is not None
            and identity.kind == "plugin"
            and identity.name != plugin
        ):
            raise CapabilityPolicyError(
                "Capability caller identity does not match the requested plugin"
            )
        if identity is not None and identity.kind == "trusted_core":
            allowed = True
            mode = "TRUSTED_CORE"
            reason = "TRUSTED_CORE"
        else:
            policy = self._cache.get(plugin)
            if policy is None:
                raise CapabilityPolicyError(
                    f"Capability policy not loaded for plugin {plugin}"
                )
            mode = policy.mode
            allowed = capability in policy.effective
            reason = "GRANT_PRESENT" if allowed else "GRANT_MISSING"
        record = {
            "plugin": plugin,
            "capability": capability,
            "operation": operation,
            "call_site": str(call_site)[:256],
            "outcome": "GRANTED" if allowed else "DENIED",
            "enforcement_mode": mode,
            "correlation_id": correlation_id,
            "reason": reason,
        }
        try:
            await self.storage.execute(
                "INSERT INTO audit_events(kind,subject_id,payload_json,created_at) "
                "VALUES (?,?,?,?)",
                (
                    "CAPABILITY_CHECK",
                    plugin,
                    json.dumps(record, separators=(",", ":"), sort_keys=True),
                    time(),
                ),
            )
        except Exception:
            # Do not let audit/authorization uncertainty become implicit access.
            logger.exception(
                "Capability audit failed plugin=%s capability=%s",
                plugin,
                capability,
            )
            raise CapabilityPolicyError(
                "Unable to persist capability authorization audit"
            ) from None
        if not allowed:
            raise CapabilityDeniedError(
                plugin, capability, operation, correlation_id=correlation_id
            )

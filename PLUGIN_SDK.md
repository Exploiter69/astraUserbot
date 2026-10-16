# AstraUserbot Plugin SDK

**SDK_API_VERSION:** `1.0`  
**Public import path:** `astra.sdk`  
**Status:** Phase 5a SDK facade

## 1. Overview

The supported plugin API is `astra.sdk`. The `core/` package remains the implementation layer. Existing plugins may continue using the compatibility API while new plugins should use the public facade.

## 2. Compatibility and versioning

The SDK API version is `1.0`. Runtime plugin API metadata is the integer `1`; the SDK adapts its version label to the canonical runtime contract. The existing `setup(client)` entry point is unchanged.

## 3. Imports and package layout

Import public contracts from `astra.sdk`. Do not depend on internal `core.*` modules for new plugins. The facade does not add a registry or lifecycle framework.

## 4. Plugin contract

Plugins structurally implement `Plugin`: module metadata attributes and `setup(client)`. Inheritance from a base class is not required. Metadata remains module-level and runtime-consumed.

## 5. Metadata declaration and validation

Use `metadata(...)` to validate metadata values, or declare the equivalent module-level fields: `plugin_name`, `plugin_version`, `plugin_api_version`, `description`, `dependencies`, `optional_dependencies`, `capabilities`, and `critical`. The runtime contract is authoritative; SDK-accepted values must not be silently dropped.

## 6. Command registration

Use `register_command`, the public alias for the existing central command registration function. It is not a second registration path.

## 7. Managed tasks

Use `tracked_task` during plugin setup for a supervised task whose cleanup belongs to the setup journal. It delegates to the existing PluginManager lifecycle.

## 8. Durable jobs

Use `tracked_job` during plugin setup when an enqueued job must be tracked for rollback. Durable execution semantics remain those of the existing JobEngine.

## 9. Managed resources

Use `tracked_resource` during plugin setup to register cleanup for resources created by setup. Cleanup remains managed by the existing setup journal.

## 10. Service protocols

The SDK exposes typing protocols for existing Telegram, HTTP, job, storage, secret, AI, and subprocess service interfaces. These are typing contracts, not runtime wrappers or a separate service container.

## 11. Capabilities and authorization

Declare only capabilities in the existing eleven-name vocabulary. A declaration is not an owner grant and is not proof that every operation is protected.

### Capability enforcement is at the service boundary

The capability check happens at the authoritative service boundary, not in the SDK handle; a plugin can call ctx.get("telegram") and reach the same object; the boundary is what enforces.

The SDK does not add authorization logic or claim to secure arbitrary in-process Python code.

## 12. Testing and local verification

Test metadata normalization, command registration and plugin behavior without live Telegram credentials. The documentation check validates this file's public API reference against `astra.sdk`.

## 13. API Reference

- `AIServiceProtocol`
- `Capability`
- `CapabilityMode`
- `CAPABILITY_NAMES`
- `EffectClass`
- `HTTPService`
- `HttpResponse`
- `JobService`
- `Plugin`
- `PluginMetadata`
- `ReconcileContext`
- `ReconcileOutcome`
- `Reconciler`
- `SDK_API_VERSION`
- `SecretStoreService`
- `StorageServiceProtocol`
- `SubprocessServiceProtocol`
- `TelegramService`
- `metadata`
- `register_command`
- `tracked_job`
- `tracked_resource`
- `tracked_task`
- `validate_capabilities`

## 14. Security boundaries, support status, and limitations

The SDK is an in-process API facade, not a sandbox. Python imports, typing, and documentation do not isolate arbitrary plugin code. Authorization depends on the existing authoritative runtime boundary.

- **Supported:** implemented and covered by acceptance tests.
- **Compatibility path:** works for existing plugins but is not the preferred new API.
- **Deferred:** not part of Phase 5a and must not be presented as available.
- **Not a security boundary:** typing, documentation and in-process handles do not isolate arbitrary Python code.

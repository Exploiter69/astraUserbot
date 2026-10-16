# AstraUserbot Plugin SDK

SDK_API_VERSION: `1.0`  
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

## 10. Generator

Create a deterministic plugin scaffold from the repository root:

```bash
python -m astra.sdk_generator create-plugin <name>
```

Use a lowercase Python package-name component (letters, digits, and underscores; it must start with a letter). The generator validates the name before writing, refuses to overwrite `plugins/<name>/` by default, and accepts `--force` only when replacement is intentional.

Generated layout:

```text
plugins/<name>/
├── __init__.py
├── plugin.py
├── README.md
└── tests/
    └── test_plugin.py
```

No manifest is generated. `plugin.py` declares the runtime-consumed module-level metadata (`plugin_name`, `plugin_version`, `plugin_api_version`, `dependencies`, `optional_dependencies`, `capabilities`, `description`, and `critical`) and implements the unchanged `setup(client)` entry point. The example capability is `telegram.read`, from the existing eleven-name vocabulary.

**A capability declaration is not enforcement.** It is metadata, not an owner grant and not proof that every operation is checked. The generated acceptance test loads the plugin through `PluginManager` without Telegram credentials; run it with `python -m pytest -q plugins/<name>/tests/test_plugin.py`. The runtime discovery path ignores conventional `tests/` directories so generated acceptance tests are not loaded as plugins.

## 11. Service protocols

The SDK exposes typing protocols for existing Telegram, HTTP, job, storage, secret, AI, and subprocess service interfaces. These are typing contracts, not runtime wrappers or a separate service container.

## 12. Capabilities and authorization

Declare only capabilities in the existing eleven-name vocabulary. A declaration is not an owner grant and is not proof that every operation is protected.

### Capability enforcement is at the service boundary

The capability check happens at the authoritative service boundary, not in the SDK handle; a plugin can call ctx.get("telegram") and reach the same object; the boundary is what enforces.

The SDK does not add authorization logic or claim to secure arbitrary in-process Python code.

## 13. Testing and local verification

Test metadata normalization, command registration and plugin behavior without live Telegram credentials. The documentation check validates this file's public API reference against `astra.sdk`.

## 14. API Reference

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

## 15. Security boundaries, support status, and limitations

The SDK is an in-process API facade, not a sandbox. Python imports, typing, and documentation do not isolate arbitrary plugin code. Authorization depends on the existing authoritative runtime boundary.

- **Supported:** implemented and covered by acceptance tests.
- **Compatibility path:** works for existing plugins but is not the preferred new API.
- **Deferred:** not part of Phase 5a and must not be presented as available.
- **Not a security boundary:** typing, documentation and in-process handles do not isolate arbitrary Python code.
- Direct `TelegramFacade` method access is not currently capability-checked; enforcement currently applies to the event-edit proxy boundary.

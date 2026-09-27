# AstraUserbot Plugin Ecosystem Contract

**Status:** Implemented
**Scope:** Discovery, metadata, dependencies, lifecycle, ownership, registration, quarantine, operator inspection, and safe runtime mutation.

## Contract

A plugin is a Python module discovered below `plugins/`. It exposes a `setup(client)` entry point. An optional `shutdown(client)` hook is used when the plugin owns long-lived resources that must be released explicitly.

The formal metadata vocabulary is:

- `plugin_name`
- `plugin_version`
- `plugin_api_version`
- `plugin_description`
- `dependencies`
- `optional_dependencies`
- `capabilities`
- `critical`

Legacy plugins remain supported through deterministic defaults (`plugin_version="legacy"`, API version 1, empty optional metadata). This is a compatibility adapter, not a second lifecycle implementation.

## Dependencies

Required dependencies are loaded before their dependents. Unknown dependencies and dependency cycles fail the load plan instead of producing partial ordering. A runtime enable operation requires every required dependency to be `RUNNING`.

Optional dependencies are informational and never block startup.

## Lifecycle

```text
DISCOVERED → LOADED → RUNNING
                 ├→ FAILED_SETUP
                 └→ DISABLED
RUNNING → UNLOADED
DISCOVERED → FAILED_IMPORT
```

Setup is executed under plugin ownership context. Command registrations created during setup are attributed to the plugin and are removed when the plugin is unloaded.

Shutdown is bounded by the existing PluginManager shutdown budget. A cancellation-resistant plugin cannot hold the whole process teardown hostage.

## Command ownership

`register_cmd()` remains the sole command registration authority. Registration records contain the plugin owner, aliases, permission, category, description, and stable registration ID. Duplicate active names/aliases are rejected.

Plugins must not maintain a parallel command registry.

## Quarantine

The four legacy AI modules remain explicitly quarantined:

- `plugins.ai.ask`
- `plugins.ai.groq_client`
- `plugins.ai.summarize`
- `plugins.ai.transcribe`

Quarantine is a hard lifecycle boundary. Runtime enable cannot bypass it.

## Safe runtime enable/disable

New lifecycle mutations use asynchronous APIs:

- `PluginManager.disable_plugin(name)`
- `PluginManager.enable_plugin(name)`

Disable refuses to remove a plugin that has running dependents. It executes plugin shutdown before applying the disabled state, so a failed shutdown does not silently leave a half-disabled plugin.

Enable requires running dependencies, refuses quarantined modules, bounds setup execution, and removes registrations created by a failed setup attempt. A failed enable leaves the plugin disabled/failed rather than partially active.

The older synchronous `disable()` / `enable()` methods remain compatibility markers for legacy callers; new operator controls must use the asynchronous APIs.

Runtime enable/disable is intentionally not persisted as a hidden configuration mutation. Persistence should be introduced only with an explicit settings contract and restart semantics.

## Operator visibility

The existing observatory exposes live plugin state through `.plugins`, including state, dependencies, criticality, errors, and owned command counts. `.status` / `.ops` surfaces failed, disabled, unloaded, and quarantined plugins.

The ecosystem audit is read-only and AST-based so auditing never requires importing arbitrary plugin code.

## Testing gate

`tools/plugin_ecosystem_audit.py` verifies the discovered active ecosystem structurally. `tests/test_plugin_ecosystem.py` covers metadata normalization, API compatibility, dependency protection, quarantine, safe lifecycle mutation, rollback, and operator metadata exposure.

A green ecosystem gate is:

```text
PLUGIN_ECOSYSTEM_QUALITY_AUDIT_PASS
```

## Post-Phase-10 operator UX

The existing PluginManager remains the lifecycle authority. The product surface exposes:

- `.plugin` — catalog;
- `.plugin <name>` — detail;
- `.plugin search <query>` — discovery;
- `.plugin health <name>` — health/lifecycle state;
- `.plugin enable <name>` — controlled activation;
- `.plugin disable <name>` — controlled disable;
- `.plugin reload <name>` — disable + enable under the same lifecycle contract;
- `.plugin install <name>` — safe local-discovered enable, not arbitrary package installation.

Compatibility, dependency, quarantine and lifecycle checks remain enforced by PluginManager.

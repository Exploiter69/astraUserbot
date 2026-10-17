# AstraUserbot Plugin SDK

## API version

Current plugin API: `1.0`.

Plugins may continue using the legacy `setup(client)` contract during migration. New plugins should declare metadata when they need explicit version/capability contracts.

```python
from astra.sdk import metadata

PLUGIN = metadata(
    name="plugins.example",
    version="1.0.0",
    capabilities=("network.external",),
    description="Example capability",
)
```

## Rules

1. Do not create a second HTTP client when `ctx.http` is sufficient.
2. Do not invoke shell helpers directly; use `ctx.subprocess`.
3. Media work uses `ctx.media` and job-owned workspaces.
4. Durable work uses `ctx.jobs`.
5. Search uses `ctx.search`.
6. Feature rollout uses `ctx.flags` when a staged rollout is justified.
7. AI uses `ctx.ai`; provider URLs/models remain outside plugins.
8. Secrets use `ctx.secrets`; never persist raw credentials in job payloads.
9. Long-lived process-local tasks use `ctx.tasks` and are never advertised as durable.
10. All user input and resource consumption remain bounded.

## Generate and test a plugin

Create a scaffold from the repository root:

```bash
python -m astra.sdk_generator create-plugin example_plugin
```

The generator creates `plugins/example_plugin/` with the plugin module, package initializer, README, and an acceptance test at `tests/test_plugin.py`. The generated `.example-plugin-info` command is an informational placeholder, not a completed feature.

Run the generated acceptance test:

```bash
python -m pytest -q plugins/example_plugin/tests/test_plugin.py
```

The generated test uses the test-only `PluginHarness` to exercise real plugin discovery, metadata loading, setup/registration, registered-wrapper command dispatch, and unload cleanup. It uses a local fake Telegram surface, requires no Telegram credentials, and denies HTTP networking by default. It does not connect to Telegram or prove that a plugin's declared capabilities are enforced. The harness is test infrastructure, not part of the public plugin runtime API.

Review the generated README and replace the placeholder handler with bounded, tested behavior before treating the plugin as feature-complete. For the full lifecycle and ecosystem contract, see [PLUGIN_ECOSYSTEM.md](PLUGIN_ECOSYSTEM.md).

## Compatibility

`astra.sdk.SDK_API_VERSION` is `"1.0"`; runtime metadata normalizes this to integer API version `1`. Unknown capabilities are rejected against the existing eleven-name vocabulary.

Legacy compatibility remains intentionally supported until a plugin has been migrated and regression-tested.

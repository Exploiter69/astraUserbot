# AstraUserbot Plugin SDK

## API version

Current plugin API: `1.0`.

Plugins may continue using the legacy `setup(client)` contract during migration. New plugins should declare metadata when they need explicit version/capability contracts.

```python
from core.sdk import metadata

PLUGIN = metadata(
    name="plugins.example",
    version="1.0.0",
    capabilities=("network.request",),
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

## Compatibility

The first semantic-version component of `api_version` must match the runtime SDK major version. A major mismatch is rejected during metadata validation.

Legacy compatibility remains intentionally supported until a plugin has been migrated and regression-tested.

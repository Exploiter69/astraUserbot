# Program E — Telegram UX + Product Expansion

**Implementation status:** complete on `main`
**Production acceptance:** pending owner-host validation

Program E is the product-expansion phase defined by `ROADMAP.md`: productivity, group management, Telegram utilities, media utilities, web/network utilities, and the consistent Telegram UX layer.

## Delivered

### E1 Productivity

Existing AFK and quick-note capabilities are retained. The new durable productivity surface adds:

- `.remind <delay> <text>`
- `.reminders`
- `.delremind <id>`
- `.bookmark [tag]` on a replied message
- `.bookmarks`
- `.unbookmark <id>`
- `.template <name> <text>`
- `.tget <name>`
- `.tlist`
- `.tdel <name>`
- `.filter add <term> <response>`
- `.filter del <id>`
- `.filter list`

Reminder state is persisted in SQLite and delivery is bounded. Filters use a per-sender cooldown and bounded rule/cache sizes. Text, name and list sizes are explicitly capped.

### E2 Group management

Existing advanced administration provides bounded purge, zombie cleanup, promotion/demotion and slow mode. The new moderation family adds:

- warn / warnings;
- mute / unmute;
- ban / unban;
- pin / unpin;
- bounded lockdown with explicit `.lockdown CONFIRM`;
- moderation audit report.

Destructive moderation is owner-controlled, refuses moderation of the owner account, and lockdown is explicitly confirmation-gated.

### E3 Telegram utilities

New practical utilities:

- `.msg` / `.inspect`
- `.id` / `.ref`
- `.link`
- `.entity`
- `.chatdiag`
- `.reply <text>`
- `.bulkdel [count]`

Bulk deletion is capped at 100 messages.

### E4 Media utilities

The existing media stack already supplies FFmpeg processing, OCR, streaming/video helpers, download/autopost and rclone integration. Program E therefore upgrades rather than duplicates that surface.

### E5 Web/network utilities

The existing network utility family already supplies DNS, HTTP headers, IP information and network diagnostics. Program E preserves those practical public-web tools rather than adding redundant network commands.

## Safety / architecture contract

- Python/asyncio modular-monolith architecture is preserved.
- SQLite remains the durable store.
- No Redis/Kafka/Celery/microservices are introduced.
- No paid service or mandatory hosted provider is introduced.
- New destructive operations are bounded and owner-controlled.
- No unauthorized active network scanning is added by Program E.
- Product commands remain deterministic and do not delegate authority to AI.

## Acceptance gate

Per the roadmap gate discipline, implementation is not called fully GREEN until the owner-host performs:

1. focused Program E tests;
2. full regression suite;
3. service restart/startup acceptance;
4. Telegram smoke of the new productivity, moderation and utility commands;
5. confirmation that existing archive/UX behavior remains intact.

The repository is ready for that acceptance pass.

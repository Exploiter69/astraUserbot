# Astra UI / Diagnostics Roadmap

## Current build

- Terminal-style Astra HUD with consistent borders and status footers.
- `.help` is a live command deck generated from the registered command patterns.
- `.help <command>` gives a focused usage card.
- `.help -m` generates a dark-theme HTML/Telegraph master manual.
- `.doctor` performs a live health audit and writes JSON diagnostics under `data/logs/`.
- `data/logs/astra.log` keeps a rotating application log with common credential-shaped values redacted.
- `.testall` performs non-destructive registry, syntax, dependency and live network checks.

## Testall safety model

`testall` deliberately does **not** automatically run commands that can delete messages, change permissions, leave chats, write to cloud remotes, alter account state, restart services, or otherwise mutate the host/account.

For safe/read-only commands it can execute an in-process synthetic smoke test using placeholder arguments. This validates the handler itself without sending a Telegram command.

Network checks are real where useful: Telegram MTProto identity lookup, DNS resolution and HTTPS reachability. External tools are checked with `PATH` discovery.

## Visual direction

Use images/GIFs selectively rather than for every response. A static HUD is faster and more reliable. Recommended future media surfaces:

1. A single optional Astra banner for `.help -m`.
2. Tiny success/failure animations only for long-running operations.
3. Progress media for downloads/transcoding where Telegram upload progress is already available.
4. No remote GIF/image dependency for core health, error, help or network responses.

This keeps the bot beautiful without making the UI dependent on a third-party CDN.

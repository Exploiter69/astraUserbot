# Plugin / Command Behavioral Audit

**Status:** Implemented; owner-host validation required before release acceptance.

This audit closes the behavioral portion of the production-hardening pass. It is intentionally separate from the plugin ecosystem contract audit: lifecycle metadata can be correct while a handler still has an unsafe edge case.

## Scope

Active plugin behavior is reviewed against:

- command argument and output bounds;
- authorization assumptions and the outgoing self-command boundary;
- direct incoming event-handler exceptions;
- shared HTTP/subprocess/media service boundaries;
- Telegram entity resolution and user-visible failure truthfulness;
- filesystem/workspace containment;
- plugin-specific persistence, cleanup, retention and concurrency;
- destructive Telegram/account operations;
- stale compatibility artifacts and misleading command contracts.

The four legacy AI modules remain quarantined and are excluded from the active-plugin behavioral surface:

- `plugins.ai.ask`
- `plugins.ai.groq_client`
- `plugins.ai.summarize`
- `plugins.ai.transcribe`

## Current hardening completed in this pass

- View-once media downloads now cross `MediaService`, so download-size, disk-space, workspace and cancellation guards apply before the payload is persisted.
- OCR downloads now cross `MediaService` instead of writing directly through the Telethon downloader.
- AI-gateway transcription downloads now use a managed media workspace; the AI gateway remains the authority for its own transcription size limit.
- Identity backup/clone now includes the documented `.backup` command, uses unique snapshot files, rejects failed current-profile snapshots before mutation, validates saved photo paths, and uploads a replacement photo before changing the existing photo state.
- PMGuard warning state is bounded in memory and strike mutation is serialized to prevent concurrent-message lost updates.
- OSINT usernames are constrained to safe path-compatible characters and the HTTP service is explicitly required.
- Doctor DNS checks no longer block the asyncio event loop; generated diagnostic reports have bounded retention; cache cleanup uses worker threads for blocking filesystem deletion.
- The historical `plugins_bundle.txt` source dump has been marked as a deprecated, non-runtime artifact so pre-hardening code cannot be mistaken for canonical source.

## Automated contract

`tools/plugin_behavior_audit.py` performs a read-only AST scan of active plugins. It must remain conservative: uncertain findings are review failures rather than silently accepted behavior.

`tests/test_plugin_behavior_contract.py` locks the important production boundaries into regression tests without importing arbitrary plugin modules.

## Acceptance

Run the normal owner-host gate after pulling the branch:

```text
pytest -q
python tools/plugin_behavior_audit.py
python tools/plugin_ecosystem_audit.py
python tools/media_pipeline_audit.py
python tools/isolation_security_audit.py
python tools/storage_hardening_audit.py
python tools/job_hardening_audit.py
python tools/phase18_production_audit.py
```

The final release gate additionally requires the real production shutdown probe and one actual `systemd stop`/restart cycle. No static audit is a substitute for those runtime checks.

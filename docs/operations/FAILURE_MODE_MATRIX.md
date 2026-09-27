# AstraUserbot — Failure-Mode Matrix

**Purpose:** deterministic first response for common production failures.  
**Rule:** failure must reduce scope, not silently broaden automation.

| Failure | Detection | Safe state | Operator response | Never do |
|---|---|---|---|---|
| Telegram disconnect | startup/logs/health | no Telegram side effects | inspect network/session; restart only when needed | regenerate/delete session blindly |
| DB integrity failure | `.health`, storage audit | stop DB mutations | stop service; preserve DB/WAL/SHM; restore known-good backup | edit rows manually |
| Migration failure/checksum mismatch | startup/migrate | old state remains authoritative | stop; inspect migration/version compatibility | alter historical migration in place |
| Plugin import failure | `.plugins` | plugin unavailable | inspect diagnostics; fix source and restart | hide/quarantine evidence as “healthy” |
| Plugin setup failure | `.plugins` | plugin unavailable | inspect dependency/config error; disable if appropriate | repeatedly restart without diagnosis |
| Command conflict | startup/audit | conflicting registration rejected | resolve ownership; retest | allow last-registration-wins |
| Task crash | `.tasks`/logs | task stopped | inspect owner/error/restart policy | create unbounded restart loop |
| Shutdown timeout | systemd/journal | process manager may terminate | inspect task/plugin/job shutdown; use bounded stop | increase systemd timeout as first fix |
| Job lease expiry | `.jobs` | `UNCERTAIN` | reconcile external effect, then explicitly requeue if safe | assume failure and duplicate mutation |
| Job retryable failure | `.jobs` | bounded `QUEUED`/retry | inspect error/backoff; allow retry | manually duplicate immediately |
| Job terminal failure | `.jobs` | `FAILED` | inspect persistent error and attempt history | mark completed without verification |
| Job payload too large | command/job error | rejected | reduce input or split intentionally | raise limits blindly |
| Media download too large | MediaService | rejected/cleaned | use smaller input or approved limit | bypass MediaService |
| Media malformed | transform/ffprobe | rejected/cleaned | report unsupported/corrupt media | run arbitrary decoder outside boundary |
| Disk exhaustion | media/storage/resource views | bounded refusal/backpressure | clean managed artifacts; free space | delete authoritative DB/source files |
| FFmpeg/ffprobe failure | media result/logs | artifact not accepted | inspect classified failure and workspace cleanup | upload unverified artifact |
| Archive traversal/link | extraction error/audit | archive rejected | preserve input if needed; report unsafe archive | extract with raw `tar`/`unzip` into production roots |
| Isolation unavailable | startup/audit | isolated feature fails closed | restore Bubblewrap or disable isolated workload | silently run same workload unsandboxed |
| Subprocess timeout | service result | child terminated | inspect command/input; retry only if safe | shell out or remove timeout |
| Subprocess output overflow | service result | output truncated/rejected | reduce verbosity/input | raise output cap indefinitely |
| HTTP timeout/rate limit | service error | request failed | honor bounded retry/Retry-After | tight retry loops |
| HTTP malformed response | adapter/service error | feature failure | classify provider failure | treat malformed data as success |
| AI provider outage | AI diagnostics/logs | AI feature degraded | use configured bounded fallback or local provider | broaden provider/URL dynamically |
| AI tool/function call | gateway rejection | response rejected | report unsupported response | execute model-supplied tool calls |
| AI budget exhausted | gateway guardrail | remote call rejected | wait for window/reset or use local provider | bypass cost/request guardrail |
| Secret exposure suspected | logs/repo/audit | treat credential compromised | stop affected service, rotate secret, preserve evidence | paste secret into issue/chat |
| Backup failure | backup command | no backup claim | inspect destination/integrity | call an unverified copy a backup |
| Restore failure | integrity/migration gate | original preserved | keep original evidence; choose another known-good backup | overwrite original blindly |
| Cache corruption | cache/search diagnostics | derived state disposable | clear/rebuild cache/index | modify authoritative records to match cache |
| Search inconsistency | `.search`/`.reindex` | index considered derived | rebuild from authoritative records | treat index as source of truth |
| Provider external mutation uncertain | job/command result | uncertain | reconcile provider state before replay | replay blindly |
| Configuration invalid | startup/config error | feature disabled/refused | correct config; retest | silently invent defaults for credentials |

## Recovery priority

1. **Contain:** stop destructive or unbounded activity.
2. **Preserve:** keep database, logs and relevant artifacts as evidence.
3. **Classify:** determine whether the failure is transport, configuration, resource, integrity, authorization, execution, or verification.
4. **Recover:** use the narrowest documented procedure.
5. **Verify:** prove the recovered state.
6. **Report:** record the commit, backup, failure class and outcome.

## Non-negotiable uncertainty rule

`UNKNOWN`, `UNCERTAIN`, or missing verification is never silently converted to success. External state must be reconciled before a potentially duplicating mutation is replayed.

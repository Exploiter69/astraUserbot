# AstraUserbot First-Run / Operator Preflight

This document closes the post-Phase-10 onboarding prerequisite for the A–H product maturity program.

## Zero-cost first run

AstraUserbot requires no paid service.

1. Clone the repository.
2. Create the local Python environment using the repository's documented development setup.
3. Configure Telegram credentials and owner identity through the existing secret/configuration boundaries.
4. Start Astra through the existing process/systemd path.
5. Run:
   - `.doctor`
   - `.status`
   - `.health`
   - `.plugins`
   - `.jobs`
6. Verify search readiness and database integrity.
7. Verify AI provider diagnostics without exposing credentials.
8. Verify isolation availability.
9. Verify plugin failures/quarantine state.
10. Only then use mutation/job commands.

## Product discovery

The primary discovery flow is:

```
.help
.help <command-or-category>
.command search <query>
.command describe <command>
.command examples <command>
.command category <category>
.command aliases <command>
.command permissions <command>
.command source <command>
.command recent
```

Unified product spine:

```
.search
   ↓
.inspect
   ↓
.correlate
   ↓
evidence
   ↓
timeline / case
   ↓
aiux explanation / report
```

## Operator recovery

If the system reports an issue:

1. run `.doctor`;
2. inspect `.status`;
3. inspect `.jobs`;
4. inspect `.plugins`;
5. rebuild derived search state with `.reindex` when search/index state is suspect;
6. reconcile `UNCERTAIN` jobs before replay;
7. use `.update check` before any update;
8. only use `.update apply` on a clean working tree;
9. restart only with explicit `.restart confirm`.

## Safety

First-run and operator flows must never:

- print secrets;
- request credentials in Telegram messages;
- bypass Telegram permissions;
- bypass traffic controls;
- install arbitrary packages;
- turn AI output into direct mutation authority;
- treat derived intelligence as identity proof.

The operator control plane is an interface over existing durable authorities. It is not a second storage or workflow system.

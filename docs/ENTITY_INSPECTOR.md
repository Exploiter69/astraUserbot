# Unified Entity Inspector

## Contract

`.inspect <target>` is the common product front door for supported entity targets.

Supported target classes include:

- URL/domain/IP/username and other IntelGraph-resolvable indicators;
- Telegram-observable entities through the existing resolver;
- IOC-prefixed targets;
- `message:<id>` search references;
- `media:<ref>` evidence references;
- `case:<id>` durable investigation cases;
- `plugin:<name>` plugin metadata;
- `command:<name>` command contracts.

## Evidence semantics

The inspector keeps these states separate:

- **OBSERVED** — directly stored observation/evidence;
- **DERIVED/CORRELATED** — relationship derived from existing observations;
- **POSSIBLE** — candidate/ambiguous result requiring further validation;
- **CONTRADICTION** — conflicting evidence;
- **UNKNOWN** — no authoritative observation available.

The inspector never promotes a weak username/relationship correlation into an identity claim.

## Correlation

`.correlate <target>` uses the existing IntelGraph correlation/graph engine. It exposes relationship type, evidence state and confidence without introducing a second graph engine.

## Search → inspect → correlate

The intended product flow is:

`search → inspect → correlate → evidence → timeline/case → AI explanation/report`

All links remain bounded and owner-scoped through the existing command and service boundaries.

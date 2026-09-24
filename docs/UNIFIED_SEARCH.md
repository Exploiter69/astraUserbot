# Unified Search Plane

`SearchService` remains the single bounded FTS5 search authority.

## Indexed domains

The rebuild path covers:

- commands;
- plugins;
- documents;
- Telegram messages/archive records;
- IntelGraph entities;
- intelligence observations;
- media-derived evidence observations;
- security-derived evidence observations;
- cases.

## Query contract

The service supports:

- bounded query length;
- bounded result count;
- deterministic ranking;
- source filtering;
- deterministic offset pagination;
- stable result IDs;
- evidence/reference IDs.

The operator `.search` surface additionally supports:

`page=N`

and

`source=A,B`

filters.

Search indexes are derived and rebuildable. They never become the authoritative source of the underlying evidence.

## Safety

The current Telegram operator surface is owner-only. Search does not grant access beyond the actor's existing Astra scope, and AI synthesis consumes only the bounded search results returned by the same service.

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
- OCR-derived evidence;
- transcript-derived evidence;
- media-derived evidence observations;
- security-derived evidence observations;
- cases.

## Query contract

The service supports:

- bounded query length;
- bounded result count;
- deterministic ranking;
- source filtering;
- stable result IDs;
- evidence/reference IDs;
- opaque query/filter-bound page cursors;
- backward-compatible offset pagination for internal callers.

A cursor cannot be reused with a different query or source-filter set.

The operator `.search` surface supports the existing bounded text-page interface and source filters. New product integrations should prefer `SearchService.search_page()` when they need stable cursor pagination.

## Result identity

Every result has:

- source;
- source reference;
- stable derived result ID;
- FTS rank;
- bounded snippet;
- evidence reference.

The index remains a derived projection. Source records remain authoritative.

## Safety

The current Telegram operator surface is owner-only. Search does not grant access beyond the actor's existing Astra scope, and AI synthesis consumes only the bounded search results returned by the same service.

Search never turns a derived match into an identity claim.

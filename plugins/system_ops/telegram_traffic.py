"""Operator diagnostics for the governed Telegram transport."""

from __future__ import annotations

import re
import time

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}(tghealth|tgtraffic|tgfloods|tgpeer|tgmethod|tgdiag)(?:\s+(.*))?$"
_MAX_ROWS = 20


def _ctx():
    context = get_application_context()
    if context is None:
        raise CommandError("Runtime context is unavailable")
    return context


def _traffic(ctx):
    try:
        return ctx.get("telegram")
    except KeyError as exc:
        raise CommandError("Telegram transport is unavailable") from exc


def _fmt_seconds(value: float | int | None) -> str:
    if value is None:
        return "—"
    value = max(0.0, float(value))
    if value < 1:
        return f"{value * 1000:.0f}ms"
    return f"{value:.1f}s"


async def _recent_rows(ctx, *, peer: str | None = None, method: str | None = None, floods: bool = False) -> list[str]:
    where: list[str] = []
    params: list[object] = []
    if peer is not None:
        where.append("peer_id = ?")
        params.append(peer)
    if method is not None:
        where.append("method = ?")
        params.append(method)
    if floods:
        where.append("result_classification IN ('FLOOD_WAIT', 'SLOW_MODE')")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = await ctx.get("storage").fetchall(
        f"SELECT timestamp,method,peer_id,operation_class,result_classification,latency_ms,"
        f"flood_wait_seconds,slow_mode_seconds,retry_count FROM telegram_operations {clause} "
        "ORDER BY timestamp DESC,id DESC LIMIT ?",
        (*params, _MAX_ROWS),
    )
    return [
        f"{method_name} · {peer_id or '—'} · {classification} · {latency:.0f}ms · retry={retries}"
        + (f" · flood={_fmt_seconds(flood)}" if flood is not None else "")
        + (f" · slow={_fmt_seconds(slow)}" if slow is not None else "")
        for _, method_name, peer_id, _, classification, latency, flood, slow, retries in rows
    ]


async def _aggregate(ctx, *, field: str, value: str | None = None) -> list[tuple]:
    if field not in {"method", "peer_id"}:
        raise ValueError("invalid aggregation field")
    if value is None:
        return await ctx.get("storage").fetchall(
            f"SELECT {field},COUNT(*),SUM(CASE WHEN result_classification='SUCCESS' THEN 1 ELSE 0 END),"
            "SUM(CASE WHEN result_classification='FLOOD_WAIT' THEN 1 ELSE 0 END),"
            "AVG(latency_ms) FROM telegram_operations "
            f"GROUP BY {field} ORDER BY COUNT(*) DESC,{field} ASC LIMIT ?",
            (_MAX_ROWS,),
        )
    return await ctx.get("storage").fetchall(
        "SELECT COUNT(*),SUM(CASE WHEN result_classification='SUCCESS' THEN 1 ELSE 0 END),"
        "SUM(CASE WHEN result_classification='FLOOD_WAIT' THEN 1 ELSE 0 END),"
        "AVG(latency_ms) FROM telegram_operations WHERE " + field + " = ?",
        (value,),
    )


async def setup(client):
    register_cmd(client, PATTERN, handle, "system_ops", "Bounded Telegram traffic, pressure and flight-recorder diagnostics.")


async def handle(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()
    ctx = _ctx()
    telegram = _traffic(ctx)
    snapshot = telegram.traffic_snapshot()

    if cmd == "tghealth":
        governor = snapshot.get("governor", {}).get("account", {})
        state = governor.get("state", "NORMAL")
        rows = [
            f"Traffic state: {state}",
            f"Active: {snapshot.get('active', 0)} / {snapshot.get('effective_concurrency', snapshot.get('max_concurrency', 0))}",
            f"Queued: {snapshot.get('queued', 0)} / {snapshot.get('max_queue', 0)}",
            f"Starved: {snapshot.get('starved', 0)}",
            f"Cooldown scopes: {len(snapshot.get('cooldowns', {}))}",
            f"Recorded: {sum(snapshot.get('counters', {}).values())}",
        ]
        await event.edit(render("TELEGRAM // HEALTH", rows, footer="system_ops | tghealth | governed transport"))
        return

    if cmd == "tgtraffic":
        rows = [
            f"State: {snapshot.get('governor', {}).get('account', {}).get('state', 'NORMAL')}",
            f"Queue: {snapshot.get('queued', 0)} / {snapshot.get('max_queue', 0)}",
            f"Active: {snapshot.get('active', 0)}",
            f"Concurrency: {snapshot.get('effective_concurrency', 0)} / {snapshot.get('max_concurrency', 0)}",
            f"Per-method: {snapshot.get('per_method_limit', 0)} · per-peer: {snapshot.get('per_peer_limit', 0)}",
            f"Starved: {snapshot.get('starved', 0)}",
            f"Counters: {', '.join(f'{k}={v}' for k, v in sorted(snapshot.get('counters', {}).items())) or 'none'}",
        ]
        await event.edit(render("TELEGRAM // TRAFFIC", rows, footer="system_ops | tgtraffic | live snapshot"))
        return

    if cmd == "tgfloods":
        rows = await _recent_rows(ctx, floods=True)
        governor = snapshot.get("governor", {})
        pressure = [
            f"{key}: {scope['state']} · pressure={scope['pressure']} · cooldown={_fmt_seconds(scope['cooldown_seconds'])}"
            for key, scope in governor.items()
            if scope.get("pressure", 0) > 0
        ][:8]
        output = [f"Pressure scopes: {len(pressure)}"] + pressure + ["", "RECENT WAITS"] + (rows or ["No FloodWait/SlowMode observations recorded."])
        await event.edit(render("TELEGRAM // FLOODS", output[:32], footer="system_ops | tgfloods | observed pressure"))
        return

    if cmd == "tgpeer":
        if not arg:
            raise CommandError("Usage: .tgpeer <peer>")
        aggregate = await _aggregate(ctx, field="peer_id", value=arg)
        if not aggregate:
            rows = [f"Peer: {arg}", "No recorded operations for this peer."]
        else:
            total, success, floods, avg = aggregate[0]
            rows = [f"Peer: {arg}", f"Operations: {total or 0}", f"Success: {success or 0}", f"FloodWait: {floods or 0}", f"Avg latency: {avg or 0:.1f}ms", "", "RECENT"] + (await _recent_rows(ctx, peer=arg) or ["No recent operations."])
        await event.edit(render("TELEGRAM // PEER", rows[:28], footer="system_ops | tgpeer | flight recorder"))
        return

    if cmd == "tgmethod":
        if not arg:
            aggregate = await _aggregate(ctx, field="method")
            rows = [
                f"{method_name or 'NULL'} · n={total} · ok={success or 0} · flood={floods or 0} · avg={avg or 0:.1f}ms"
                for method_name, total, success, floods, avg in aggregate
            ] or ["No recorded Telegram operations."]
        else:
            aggregate = await _aggregate(ctx, field="method", value=arg)
            if not aggregate:
                rows = [f"Method: {arg}", "No recorded operations for this method."]
            else:
                total, success, floods, avg = aggregate[0]
                rows = [f"Method: {arg}", f"Operations: {total or 0}", f"Success: {success or 0}", f"FloodWait: {floods or 0}", f"Avg latency: {avg or 0:.1f}ms", "", "RECENT"] + (await _recent_rows(ctx, method=arg) or ["No recent operations."])
        await event.edit(render("TELEGRAM // METHOD", rows[:28], footer="system_ops | tgmethod | flight recorder"))
        return

    recent = await _recent_rows(ctx)
    governor = snapshot.get("governor", {}).get("account", {})
    rows = [
        f"Generated: {int(time.time())}",
        f"Governor: {governor.get('state', 'NORMAL')} · pressure={governor.get('pressure', 0)} · cooldown={_fmt_seconds(governor.get('cooldown_seconds'))}",
        f"Queue: {snapshot.get('queued', 0)} / {snapshot.get('max_queue', 0)}",
        f"Active: {snapshot.get('active', 0)} / {snapshot.get('max_concurrency', 0)}",
        f"Effective concurrency: {snapshot.get('effective_concurrency', 0)}",
        f"Cooldown scopes: {len(snapshot.get('cooldowns', {}))}",
        "",
        "RECENT OPERATIONS",
    ] + (recent or ["No recorded operations."])
    await event.edit(render("TELEGRAM // DIAGNOSTICS", rows[:30], footer="system_ops | tgdiag | bounded diagnostics"))

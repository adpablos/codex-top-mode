"""Read local agent logs: token totals per model and a quota-based suggestion.

Read-only. Prints counts only: no prompts, paths, session or account IDs.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from usage_monitor import epoch, expiry_advice, number, snapshot, weekly

WEEK_MINUTES = 10080
CODEX_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
# Codex names a rollout after its local start time, with no UTC offset.
ROLLOUT_START = re.compile(r"rollout-(\d{4}-\d\d-\d\d)T(\d\d)-(\d\d)-(\d\d)")
CLAUDE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def agent_home(variable, folder):
    """Where an agent keeps its data: its environment override, else ~/<folder>."""
    return Path(os.environ.get(variable) or Path.home() / folder).expanduser()


def iso(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def lines(path, markers):
    """Yield parsed JSON lines that contain one of the markers."""
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if any(marker in line for marker in markers):
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        yield row
    except OSError:
        return


def recent_files(roots, pattern, since):
    """Session files modified at or after `since`, newest first."""
    found = []
    for root in roots:
        if root.is_dir():
            for path in root.rglob(pattern):
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if modified >= since:
                    found.append((modified, path))
    return [path for _, path in sorted(found, reverse=True)]


def add(bucket, usage, fields):
    for field in fields:
        value = usage.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            bucket[field] = bucket.get(field, 0) + int(value)


def codex_tokens(home, since, until):
    """Sum per-response usage from Codex rollout logs, attributed to model/effort."""
    roots = [home / "sessions", home / "archived_sessions"]
    buckets, sessions, responses, older = {}, 0, 0, 0
    for path in recent_files(roots, "rollout-*.jsonl", since):
        model, effort, seen, used = "unknown", None, set(), False
        records = any(True for _ in lines(path, ('"token_usage_record"',)))
        previous = None
        for row in lines(path, ('"turn_context"', '"token_usage_record"', '"token_count"')):
            kind, payload = row.get("type"), row.get("payload") or {}
            if kind == "turn_context":
                model = payload.get("model") or model
                effort = payload.get("effort") or effort
                continue
            stamp = epoch(row.get("timestamp"))
            if records and kind == "token_usage_record":
                usage, key = payload.get("usage") or {}, payload.get("response_id")
                if key in seen or stamp is None or not since <= stamp <= until:
                    continue
                seen.add(key)
            elif not records and payload.get("type") == "token_count":
                # Older logs: derive per-event usage from the cumulative counter.
                total = (payload.get("info") or {}).get("total_token_usage")
                if not isinstance(total, dict):
                    continue
                before, previous = previous, total
                if stamp is None or not since <= stamp <= until:
                    continue
                usage = {
                    f: total.get(f, 0) - (before or {}).get(f, 0) for f in CODEX_FIELDS
                }
                if before and total.get("total_tokens", 0) < before.get("total_tokens", 0):
                    usage = total
                if usage.get("total_tokens", 0) <= 0:
                    continue
            else:
                continue
            bucket = buckets.setdefault((model, effort), {"responses": 0})
            bucket["responses"] += 1
            add(bucket, usage, CODEX_FIELDS)
            responses += 1
            used = True
        sessions += used
        if used and not records:
            # The older format only keeps a cumulative counter, which can leave out
            # automatic compactions, so a total that includes it may be a lower bound.
            older += 1
    result = summary("codex", buckets, sessions, responses)
    result["olderLogs"] = older
    # Codex compresses logs untouched for a week (.jsonl.zst); stdlib Python cannot read them.
    packed = recent_files(roots, "rollout-*.jsonl.zst", since)
    result["compressedLogs"] = sum(not started_after(path, until) for path in packed)
    return result


def started_after(path, until):
    """Whether a rollout's name proves it started after `until`.

    The name gives local time without an offset; no offset exceeds 14 hours.
    """
    match = ROLLOUT_START.match(path.name)
    start = match and epoch("{}T{}:{}:{}+00:00".format(*match.groups()))
    return bool(start) and start - 14 * 3600 > until


def claude_tokens(home, since, until):
    """Sum assistant message usage from Claude Code transcripts, once per message."""
    buckets, sessions, seen = {}, set(), set()
    for path in recent_files([home / "projects"], "*.jsonl", since):
        for row in lines(path, ('"usage"',)):
            message = row.get("message")
            if row.get("type") != "assistant" or not isinstance(message, dict):
                continue
            usage, model = message.get("usage"), message.get("model")
            stamp = epoch(row.get("timestamp"))
            key = message.get("id") or row.get("requestId") or row.get("uuid")
            if (
                not isinstance(usage, dict)
                or not model
                or model.startswith("<")
                or key in seen
                or stamp is None
                or not since <= stamp <= until
            ):
                continue
            seen.add(key)
            # Subagents share their parent's sessionId; each has its own agentId.
            sessions.add((row.get("sessionId") or path.stem, row.get("agentId")))
            groups = {}
            for step_model, step in claude_steps(usage, model):
                effort = row.get("effort") if step_model == model else None
                groups.setdefault((step_model, effort), []).append(step)
            for group, steps in groups.items():
                bucket = buckets.setdefault(group, {"responses": 0})
                bucket["responses"] += 1
                for step in steps:
                    add(bucket, step, CLAUDE_FIELDS)
    for bucket in buckets.values():
        bucket["total_tokens"] = sum(bucket.get(f, 0) for f in CLAUDE_FIELDS)
    return summary("claude", buckets, len(sessions), len(seen))


def claude_steps(usage, model):
    """The billed steps of one response, as (model, usage) pairs.

    `usage.iterations` itemizes them (a server-side advisor call, a compaction, a
    retried attempt), each under its own model when it names one; the top-level
    counts can leave those steps out. Older transcripts have no iterations.
    """
    steps = usage.get("iterations")
    if not isinstance(steps, list) or not steps:
        return [(model, usage)]
    return [(s.get("model") or model, s) for s in steps if isinstance(s, dict)]


def summary(provider, buckets, sessions, responses):
    models = [
        {"model": model, "effort": effort, **values}
        for (model, effort), values in sorted(
            buckets.items(), key=lambda item: -item[1].get("total_tokens", 0)
        )
    ]
    return {
        "provider": provider,
        "sessions": sessions,
        "responses": responses,
        "totalTokens": sum(m.get("total_tokens", 0) for m in models),
        "byModel": models,
    }


def codex_quota(home):
    """Newest weekly/5-hour reading that Codex wrote into its local session logs.

    The most recently modified log can hold only old readings (a long session
    that keeps logging other events), so readings are compared by their own time.
    A log last modified before the best reading so far cannot hold a newer one.
    However old the newest reading is, it is returned, so advise() can call it stale.
    """
    best = None
    roots = [home / "sessions", home / "archived_sessions"]
    for path in recent_files(roots, "rollout-*.jsonl", 0):
        if best and path.stat().st_mtime < best[0]:
            break
        for row in lines(path, ('"rate_limits"',)):
            limits = (row.get("payload") or {}).get("rate_limits")
            stamp = epoch(row.get("timestamp"))
            if (
                isinstance(limits, dict)
                # Model-specific buckets (codex_<model>) are not the account's allowance.
                and limits.get("limit_id") in (None, "codex")
                and stamp
                and (best is None or stamp > best[0])
            ):
                best = (stamp, row["timestamp"], limits)
    if best is None:
        return None
    _, stamp, limits = best
    payload = {
        "rateLimitsByLimitId": {
            "codex": {
                slot: {
                    "usedPercent": window.get("used_percent"),
                    "windowDurationMins": window.get("window_minutes"),
                    "resetsAt": window.get("resets_at"),
                }
                for slot in ("primary", "secondary")
                if isinstance(window := limits.get(slot), dict)
            }
        }
    }
    return {"source": "codex_session_log", **snapshot(payload, stamp)}


def file_quota(path, observed_at=None):
    """A saved Claude Code status-line JSON or a native Codex usage payload.

    The capture time is observed_at or the file's own {"observedAt", "payload"}
    wrapper, never the file's modification time, which copies and restores change.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "payload" in data:
        observed_at = observed_at or data.get("observedAt")
        data = data["payload"]
    if epoch(observed_at) is None:
        raise ValueError("The reading has no capture time; pass --observed-at")
    limits = data.get("rate_limits") if isinstance(data, dict) else None
    if isinstance(limits, dict) and ("seven_day" in limits or "five_hour" in limits):
        windows = []
        for name, minutes in (("five_hour", 300), ("seven_day", WEEK_MINUTES)):
            window = limits.get(name)
            used = window.get("used_percentage") if isinstance(window, dict) else None
            if number(used) is not None and 0 <= used <= 100:
                windows.append(
                    {
                        "slot": name,
                        "usedPercent": float(used),
                        "durationMinutes": minutes,
                        "resetsAt": epoch(window.get("resets_at")),
                    }
                )
        return {
            "source": "claude_status_line",
            "observedAt": observed_at,
            "windows": windows,
            "availableResets": None,
            "grantTimes": [],
            "resetExpirations": [],
        }
    return {"source": "codex_usage_payload", **snapshot(data, observed_at)}


def advise(reading, now, min_unused=25, within_hours=36, stale_hours=6):
    """Suggest, never start: unused weekly quota near renewal or expiring resets."""
    if reading is None:
        return {"suggestion": "unknown", "reasons": ["no_quota_reading"]}
    observed = epoch(reading["observedAt"])
    # Decisions use exact hours; only the reported values are rounded.
    age, hours = (now - observed) / 3600, None
    result = {
        "source": reading["source"],
        "observedAt": iso(observed),
        "readingAgeHours": round(age, 1),
        "weeklyUsedPercent": None,
        "weeklyResetsAt": None,
        "hoursToWeeklyReset": None,
        "reasons": [],
    }
    week = weekly(reading)
    if week:
        result["weeklyUsedPercent"] = week["usedPercent"]
        if week["resetsAt"] is not None:
            hours = (week["resetsAt"] - now) / 3600
            result["weeklyResetsAt"] = iso(week["resetsAt"])
            result["hoursToWeeklyReset"] = round(hours, 1)
    if age > stale_hours:
        result["reasons"].append("reading_is_stale")
    elif observed > now + 300:
        # A capture time ahead of the clock is a wrong date, not a fresh reading.
        result["reasons"].append("reading_time_in_the_future")
    if week is None:
        result["reasons"].append("weekly_window_unknown")
    elif hours is not None and hours <= 0:
        # The window this reading describes has already renewed.
        result["reasons"].append("weekly_window_renewed_since_reading")
    elif week["usedPercent"] >= 100:
        result["reasons"].append("weekly_limit_reached")
    elif hours is not None and 0 < hours <= within_hours and 100 - week["usedPercent"] >= min_unused:
        result["reasons"].append("unused_weekly_quota_before_reset")
    expiring = expiry_advice({**reading, "observedAt": now})
    if expiring["dueExpirations"]:
        result["reasons"].append("saved_resets_expiring_soon")
        result["expiringResets"] = [iso(t) for t in expiring["dueExpirations"]]
    good = {"unused_weekly_quota_before_reset", "saved_resets_expiring_soon"}
    blocked = {
        "weekly_limit_reached",
        "weekly_window_renewed_since_reading",
        "reading_is_stale",
        "reading_time_in_the_future",
    }
    if blocked & set(result["reasons"]):
        result["suggestion"] = "refresh_or_wait"
    elif good & set(result["reasons"]):
        result["suggestion"] = "consider_top_mode"
    elif week is None:
        result["suggestion"] = "unknown"
    else:
        result["suggestion"] = "nothing_to_do"
    return result


def markdown(report):
    out = [f"Tokens from {report['since']} to {report['until']} (local logs)", ""]
    out.append("| Agent | Model | Effort | Responses | Total tokens | Detail |")
    out.append("| --- | --- | --- | ---: | ---: | --- |")
    for provider in report["providers"]:
        for row in provider["byModel"]:
            detail = ", ".join(
                f"{k.replace('_tokens', '').replace('_', ' ')} {v:,}"
                for k, v in row.items()
                if k.endswith("_tokens") and k != "total_tokens"
            )
            out.append(
                f"| {provider['provider']} | {row['model']} | {row['effort'] or '-'} "
                f"| {row['responses']:,} | {row.get('total_tokens', 0):,} | {detail} |"
            )
        if not provider["byModel"]:
            out.append(f"| {provider['provider']} | none found | - | 0 | 0 | |")
    out.append("")
    for provider in report["providers"]:
        out.append(
            f"- {provider['provider']}: {provider['sessions']} sessions, "
            f"{provider['totalTokens']:,} tokens"
        )
        if provider.get("olderLogs"):
            out.append(
                f"  {provider['olderLogs']} of its logs in this interval use an older format "
                "that can leave out automatic compactions, so this total may be a lower bound."
            )
        if provider.get("compressedLogs"):
            out.append(
                f"  {provider['compressedLogs']} compressed logs that may cover this interval "
                "were not read, so this total may be a lower bound."
            )
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tokens = commands.add_parser("tokens", help="Token totals per agent and model")
    tokens.add_argument("--since", required=True, help="ISO time with timezone")
    tokens.add_argument("--until", help="ISO time with timezone (default: now)")
    tokens.add_argument("--markdown", action="store_true")
    quota = commands.add_parser("quota", help="Latest quota reading and a suggestion")
    quota.add_argument("--file", help="Saved Claude status-line JSON or Codex payload")
    quota.add_argument("--observed-at", help="When --file was captured, if it doesn't say")
    quota.add_argument("--min-unused", type=float, default=25)
    quota.add_argument("--within-hours", type=float, default=36)
    for command in (tokens, quota):
        command.add_argument("--codex-home", type=Path, default=agent_home("CODEX_HOME", ".codex"))
        command.add_argument(
            "--claude-home", type=Path, default=agent_home("CLAUDE_CONFIG_DIR", ".claude")
        )
    args = parser.parse_args()
    now = time.time()
    if args.command == "tokens":
        since = epoch(args.since)
        until = epoch(args.until) if args.until else now
        if since is None or until is None or since > until:
            parser.error("Use ISO times with a timezone, --since before --until")
        report = {
            "since": iso(since),
            "until": iso(until),
            "providers": [
                codex_tokens(args.codex_home, since, until),
                claude_tokens(args.claude_home, since, until),
            ],
        }
        print(markdown(report) if args.markdown else json.dumps(report, indent=2))
        return
    if args.file:
        if args.observed_at and epoch(args.observed_at) is None:
            parser.error("--observed-at needs an ISO time with a timezone")
        try:
            reading = file_quota(args.file, args.observed_at)
        except (OSError, ValueError) as error:
            parser.error(f"Cannot use {args.file}: {error}")
    else:
        reading = codex_quota(args.codex_home)
    json.dump(advise(reading, now, args.min_unused, args.within_hours), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()

"""Read-only quota readings: keep only window percentages, lengths, renewal times
and saved-reset counts and expiries; never redeem a reset."""

import json
import math
import os
import tempfile
from datetime import datetime


def epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except ValueError:
            return None
    return None


def number(value):
    return epoch(value) if not isinstance(value, str) else None


def snapshot(payload, observed_at):
    """Allowlist fields: no account IDs, credit IDs, balances or credentials."""
    if epoch(observed_at) is None:
        raise ValueError("An explicit observation time with a timezone is required")
    if not isinstance(payload, dict) or payload.get("isError"):
        payload = {}
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict):
        legacy = payload.get("rateLimits")
        buckets = {"codex": legacy} if isinstance(legacy, dict) else {}
    windows = []
    bucket = buckets.get("codex")
    if isinstance(bucket, dict):
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            used = number(window.get("usedPercent"))
            duration = number(window.get("windowDurationMins"))
            reset_at = number(window.get("resetsAt"))
            if used is not None and 0 <= used <= 100 and duration and duration > 0:
                windows.append(
                    {
                        "slot": slot,
                        "usedPercent": used,
                        "durationMinutes": duration,
                        "resetsAt": reset_at,
                    }
                )
    resets = payload.get("rateLimitResetCredits")
    resets = resets if isinstance(resets, dict) else {}
    count = number(resets.get("availableCount"))
    if count is not None and (count < 0 or count != int(count)):
        count = None
    details = resets.get("credits")
    grants = []
    expirations = []
    for row in details if isinstance(details, list) else []:
        if isinstance(row, dict) and row.get("status") == "available":
            granted = number(row.get("grantedAt"))
            if granted is not None:
                grants.append(granted)
            expires = number(row.get("expiresAt"))
            if expires is not None:
                expirations.append({"grantedAt": granted, "expiresAt": expires})
    return {
        "observedAt": observed_at,
        "windows": windows,
        "availableResets": count,
        "grantTimes": sorted(set(grants)),
        "resetExpirations": expirations,
    }


def expiry_advice(observation, warning_days=7):
    """Use actual available-credit expirations; never infer a default lifetime."""
    now = epoch(observation["observedAt"])
    if now is None:
        raise ValueError("An explicit observation time is required")
    rows = observation.get("resetExpirations", [])
    if observation.get("availableResets") == 0:
        rows = []
    future = sorted({r["expiresAt"] for r in rows if r["expiresAt"] > now})
    due = [t for t in future if t - now <= warning_days * 86400]
    count = observation.get("availableResets")
    known = len({(r.get("grantedAt"), r["expiresAt"]) for r in rows if r["expiresAt"] > now})
    coverage = "unknown"
    if count is not None:
        coverage = "complete" if known >= count else "partial"
    return {
        "warningDays": warning_days,
        "dueExpirations": due,
        "nextWarningAt": min(
            (t - warning_days * 86400 for t in future if t not in due), default=None
        ),
        "expiryCoverage": coverage,
        "knownAvailableExpirations": known,
        "availableResets": count,
    }


def weekly(observation):
    return next((w for w in observation["windows"] if w["durationMinutes"] == 10080), None)


def write_private(path, state):
    handle, name = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

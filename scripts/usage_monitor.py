"""Classify read-only Codex usage observations; never redeem a reset."""

import argparse
import copy
import json
import math
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path


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


def replenished(anchor, current, detect_low_usage_shift=False):
    decrease = anchor["usedPercent"] - current["usedPercent"]
    strong_decrease = current["usedPercent"] <= max(2, anchor["usedPercent"] / 4) and decrease >= 5
    old_reset, new_reset = epoch(anchor.get("resetsAt")), epoch(current.get("resetsAt"))
    shifted_low_decrease = (
        detect_low_usage_shift
        and 0 < decrease < 5
        and current["usedPercent"] <= 2
        and old_reset is not None
        and new_reset is not None
        and new_reset > old_reset
    )
    return strong_decrease or shifted_low_decrease


def observe(monitor, current):
    """Two fresh off-schedule weekly observations stop new intensive batches."""
    result = copy.deepcopy(monitor)
    now = epoch(current.get("observedAt"))
    if now is None:
        raise ValueError("An explicit observation time is required")
    if result.get("mode") == "normal":
        result.setdefault("stoppedAt", current["observedAt"])
        return result, "already_normal"
    deadline = epoch(result.get("effectiveStopAt"))
    if deadline is None:
        raise ValueError("A valid authorized stop time is required")
    scheduled_stop = epoch(result.get("scheduledWeeklyStopAt"))
    if result.get("stopOnScheduledWeeklyRenewal") and scheduled_stop is None:
        anchor = weekly(result.get("baseline", result.get("last", {"windows": []})))
        scheduled_stop = epoch(anchor.get("resetsAt")) if anchor else None
    if (
        result.get("stopOnScheduledWeeklyRenewal")
        and scheduled_stop is not None
        and scheduled_stop <= deadline
        and now >= scheduled_stop
    ):
        result["mode"] = "normal"
        result["stopReason"] = "scheduled_weekly_renewal_due"
        result["stoppedAt"] = scheduled_stop
        return result, "scheduled_weekly_renewal_due"
    if now >= deadline:
        result["mode"] = "normal"
        result["stopReason"] = "authorized_time_window_ended"
        result["stoppedAt"] = result["effectiveStopAt"]
        result.setdefault("events", []).append(
            {"observedAt": current["observedAt"], "event": "time_window_ended"}
        )
        result["events"] = result["events"][-16:]
        return result, "time_window_ended"
    previous = result.get("last")
    if previous and now <= epoch(previous["observedAt"]):
        return result, "stale_observation"
    event = "unchanged"
    if previous:
        before_count = result.get("lastAvailableResets", previous["availableResets"])
        count = current["availableResets"]
        count_increased = before_count is not None and count is not None and count > before_count
        known_grants = result.get("seenGrantTimes", previous["grantTimes"])
        initial_time = epoch(result.get("baseline", previous)["observedAt"])
        new_grant = count != 0 and any(
            g > initial_time and g not in known_grants for g in current["grantTimes"]
        )
        if count_increased or new_grant:
            # Reported, never used to extend the deadline.
            result["bankedResetObserved"] = True
            event = "banked_reset_added"
        old, new = result.get("lastWeekly", weekly(previous)), weekly(current)
        detect_low_usage_shift = result.get("detectLowUsageRenewalShift", False)
        candidate = result.get("pendingReplenishment")
        if candidate and new:
            confirmed_drop = replenished(candidate["anchor"], new, detect_low_usage_shift)
            age = now - candidate["firstSeenAt"]
            anchor_reset = candidate["anchor"]["resetsAt"]
            if anchor_reset is not None and now >= anchor_reset - 60:
                result["pendingReplenishment"] = None
                if confirmed_drop:
                    event = "scheduled_weekly_reset"
            elif 20 <= age <= 1800 and confirmed_drop:
                result["mode"] = "normal"
                result["stopReason"] = (
                    "weekly_quota_replenished_before_expected_reset"
                    if anchor_reset is not None
                    else "weekly_quota_replenished"
                )
                result["stoppedAt"] = current["observedAt"]
                event = "quota_replenishment_confirmed"
            elif not confirmed_drop:
                result["pendingReplenishment"] = None
            elif age > 1800:
                candidate["firstSeenAt"] = now
                event = "confirm_replenishment_with_fresh_read"
        if (
            result.get("mode") != "normal"
            and not result.get("pendingReplenishment")
            and old
            and new
            and replenished(old, new, detect_low_usage_shift)
        ):
            if old["resetsAt"] is None or now < old["resetsAt"] - 60:
                result["pendingReplenishment"] = {"firstSeenAt": now, "anchor": old}
                event = "confirm_replenishment_with_fresh_read"
            else:
                event = "scheduled_weekly_reset"
    result["last"] = current
    result.setdefault("baseline", previous or current)
    if weekly(current):
        result["lastWeekly"] = weekly(current)
    if current["availableResets"] is not None:
        result["lastAvailableResets"] = current["availableResets"]
    result["seenGrantTimes"] = sorted(
        set(result.get("seenGrantTimes", []) + current["grantTimes"])
    )[-16:]
    if not current["windows"] and event == "unchanged":
        event = "usage_unavailable"
    if event not in ("unchanged", "usage_unavailable"):
        result.setdefault("events", []).append(
            {"observedAt": current["observedAt"], "event": event}
        )
        result["events"] = result["events"][-16:]
    return result, event


def stop_new_work_at(monitor):
    if monitor.get("mode") == "normal":
        return monitor.get("stoppedAt")
    stop = monitor.get("effectiveStopAt")
    if monitor.get("stopOnScheduledWeeklyRenewal"):
        scheduled = monitor.get("scheduledWeeklyStopAt")
        if epoch(scheduled) is None:
            anchor = weekly(monitor.get("baseline", monitor.get("last", {"windows": []})))
            scheduled = anchor.get("resetsAt") if anchor else None
        if (
            epoch(scheduled) is not None
            and epoch(stop) is not None
            and epoch(scheduled) < epoch(stop)
        ):
            return scheduled
    return stop


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    payload = json.load(sys.stdin)
    current = snapshot(payload, args.observed_at)
    monitor, event = observe(state["usageMonitor"], current)
    state["usageMonitor"] = monitor
    state["stopNewWorkAt"] = stop_new_work_at(monitor)
    state["lastUpdatedAt"] = args.observed_at
    write_private(args.state, state)
    print(
        json.dumps(
            {
                "event": event,
                "mode": monitor["mode"],
                "stopReason": monitor.get("stopReason"),
                "effectiveStopAt": monitor["effectiveStopAt"],
                "stopNewWorkAt": state["stopNewWorkAt"],
                "availableResets": current["availableResets"],
                "weeklyUsedPercent": (weekly(current) or {}).get("usedPercent"),
                "expiryAdvice": expiry_advice(current),
            }
        )
    )


if __name__ == "__main__":
    main()

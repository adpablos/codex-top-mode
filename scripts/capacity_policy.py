"""Validate a human-approved capacity profile and classify a local preflight."""

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from usage_monitor import (
    epoch,
    number,
    observe,
    snapshot,
    stop_new_work_at,
    weekly,
    write_private,
)

ACTIONS = {
    "read",
    "edit",
    "checks",
    "commit",
    "publish_pr",
    "review",
    "merge",
    "install",
    "access",
    "finance",
    "destruction",
    "redeem_reset",
}
MECHANISMS = {"banked_reset", "automatic_restoration", "mixed", "unspecified"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def public_url(value: str) -> str:
    require(text(value) and len(value) <= 2048, "A public source URL is required")
    url = urlsplit(value)
    require(
        url.scheme == "https"
        and bool(url.hostname)
        and not url.username
        and not url.password
        and url.port in (None, 443),
        "Sources must be HTTPS URLs without credentials",
    )
    decoded_path = unquote(url.path)
    require(
        "//" not in decoded_path
        and "\\" not in decoded_path
        and not any(part in {".", ".."} for part in decoded_path.split("/")),
        "Source paths must not contain ambiguous segments",
    )
    host, path = url.netloc.lower().removesuffix(":443"), url.path.rstrip("/")
    if url.hostname.lower() in {"x.com", "twitter.com"}:
        match = re.fullmatch(
            r"/([A-Za-z0-9_]{1,15})(?:/status/([0-9]+)(?:/(?:photo|video)/[0-9]+)?)?/?",
            decoded_path,
        )
        require(match is not None, "A canonical X profile or post URL is required")
        host, path = "x.com", "/" + match[1].lower()
        if match[2] is not None:
            path += "/status/" + match[2]
    return urlunsplit(("https", host, path, "", ""))


def validate_profile(profile: dict) -> None:
    require(
        isinstance(profile, dict)
        and type(profile.get("schemaVersion")) is int
        and profile["schemaVersion"] == 1,
        "Unsupported profile version",
    )
    for key in ("authorization", "sources", "projects", "actions", "limits"):
        require(isinstance(profile.get(key), dict), f"Missing profile section: {key}")
    auth = profile["authorization"]
    approved, expires = epoch(auth.get("approvedAt")), epoch(auth.get("validUntil"))
    require(
        text(auth.get("source"))
        and approved is not None
        and "validUntil" in auth
        and (auth["validUntil"] is None or (expires is not None and approved < expires)),
        "Human authorization needs an explicit expiration policy",
    )
    require(type(auth.get("conditionalStart")) is bool, "conditionalStart must be boolean")
    require(
        type(auth.get("allowUnspecifiedUpcoming", False)) is bool,
        "allowUnspecifiedUpcoming must be boolean",
    )
    sources = profile["sources"]
    for key in ("announcements", "backlog"):
        require(
            isinstance(sources.get(key), list)
            and sources[key]
            and all(text(v) for v in sources[key]),
            f"Missing {key} sources",
        )
    for url in sources["announcements"]:
        public_url(url)
    projects = profile["projects"]
    require(bool(projects), "At least one named project is required")
    for project, config in projects.items():
        require(
            text(project)
            and isinstance(config, dict)
            and text(config.get("label"))
            and isinstance(config.get("contextSources"), list)
            and all(text(v) for v in config["contextSources"]),
            "Invalid project context",
        )
    excluded = profile.get("excludedProjects")
    require(
        isinstance(excluded, list) and all(text(p) and p in projects for p in excluded),
        "Exclusions must name registered projects",
    )
    actions = profile["actions"]
    require(
        bool(actions)
        and all(
            k in ACTIONS and isinstance(v, str) and v in {"allowed", "ask", "deny"}
            for k, v in actions.items()
        ),
        "Invalid action policy",
    )
    require(
        actions.get("redeem_reset", "deny") != "allowed",
        "Reset redemption always requires current human confirmation",
    )
    limits = profile["limits"]
    for key in ("maximumHours", "announcementMaxAgeHours"):
        value = number(limits.get(key))
        require(value is not None and value > 0, f"Invalid limit: {key}")
    require(
        type(limits.get("maximumActiveThreads")) is int and limits["maximumActiveThreads"] > 0,
        "Invalid active-thread limit",
    )
    require(
        type(limits.get("stopOnScheduledWeeklyRenewal")) is bool,
        "The scheduled-weekly-renewal policy must be explicit",
    )
    tiers = limits.get("modelTiers")
    require(
        isinstance(tiers, dict)
        and set(tiers) == {"repeatable", "ordinary", "difficult"}
        and all(text(v) for v in tiers.values()),
        "Three model tiers are required",
    )
    backlog = profile.get("backlog")
    require(isinstance(backlog, list), "A backlog list is required")
    ids = set()
    for task in backlog:
        require(isinstance(task, dict), "Invalid backlog item")
        require(
            all(
                text(task.get(k))
                for k in ("id", "project", "objective", "benefit", "doneWhen", "owner")
            ),
            "Backlog items require a goal, benefit, completion criterion and owner",
        )
        require(
            task["id"] not in ids and task["project"] in projects,
            "Task IDs must be unique and projects registered",
        )
        ids.add(task["id"])
        require(
            type(task.get("ready")) is bool
            and "blocker" in task
            and (task.get("blocker") is None or text(task["blocker"])),
            "Invalid readiness",
        )
        require(
            isinstance(task.get("status"), str)
            and task["status"] in {"pending", "in_progress", "done"}
            and type(task.get("priority")) is int
            and task["priority"] >= 0,
            "Invalid task status or priority",
        )


def action_decision(profile: dict, project: str, action: str) -> str:
    """A policy ceiling, never a replacement for action-specific consent."""
    validate_profile(profile)
    if project not in profile["projects"] or project in profile["excludedProjects"]:
        return "deny"
    return profile["actions"].get(action, "deny")


def ready_work(profile: dict) -> list[str]:
    busy = {t["owner"] for t in profile["backlog"] if t["status"] == "in_progress"}
    slots = max(
        0,
        profile["limits"]["maximumActiveThreads"]
        - sum(t["status"] == "in_progress" for t in profile["backlog"]),
    )
    if not slots:
        return []
    chosen = []
    for task in sorted(profile["backlog"], key=lambda t: (t["priority"], t["id"])):
        if (
            task["status"] == "pending"
            and task["ready"]
            and not task["blocker"]
            and task["project"] not in profile["excludedProjects"]
            and task["owner"] not in busy
        ):
            chosen.append(task["id"])
            busy.add(task["owner"])
            if len(chosen) == slots:
                break
    return chosen


def fingerprint(profile: dict) -> str:
    fields = {
        k: profile[k]
        for k in (
            "authorization",
            "sources",
            "projects",
            "excludedProjects",
            "actions",
            "limits",
        )
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def announcement(profile: dict, event: dict, now: float) -> dict:
    require(isinstance(event, dict), "An announcement envelope is required")
    url = public_url(event.get("sourceUrl"))
    sources = [public_url(s).casefold() for s in profile["sources"]["announcements"]]
    require(
        any(url.casefold() == s or url.casefold().startswith(s + "/") for s in sources),
        "Announcement publisher is outside the approved sources",
    )
    published = epoch(event.get("publishedAt"))
    verification = event.get("verification", {})
    require(isinstance(verification, dict), "Invalid announcement verification")
    verified = epoch(verification.get("verifiedAt"))
    require(
        verification.get("method") == "primary_source_read"
        and published is not None
        and verified is not None
        and published <= verified <= now,
        "Read the primary post and verify its publication time and mechanism",
    )
    require(
        isinstance(event.get("mechanism"), str) and event["mechanism"] in MECHANISMS,
        "Unknown announcement mechanism",
    )
    require(
        event.get("announcementStatus") in ("upcoming", "applied"),
        "Announcement must distinguish upcoming from applied",
    )
    require(
        epoch(profile["authorization"]["approvedAt"]) < published <= now,
        "Announcements published before authorization cannot activate work",
    )
    require(
        now - published <= profile["limits"]["announcementMaxAgeHours"] * 3600,
        "Announcement is too old for conditional activation",
    )
    expected = epoch(event.get("expectedResetAt"))
    if event.get("expectedResetAt") is not None:
        require(
            expected is not None and expected > now,
            "An explicit expected reset time must be valid and future",
        )
    return {
        "sourceUrl": url,
        "publishedAt": published,
        "verifiedAt": verified,
        "mechanism": event["mechanism"],
        "announcementStatus": event["announcementStatus"],
        "expectedResetAt": expected,
        "id": hashlib.sha256(url.casefold().encode()).hexdigest(),
    }


def preflight(profile: dict, state: dict, current: dict, event=None) -> tuple[dict, dict]:
    """Pure transition: no scheduler, dispatcher, network or reset client."""
    validate_profile(profile)
    candidates = ready_work(profile)
    require(isinstance(state, dict), "Invalid state envelope")
    now = epoch(current.get("observedAt"))
    require(now is not None, "A fresh local observation time is required")
    result = copy.deepcopy(state)
    auth = profile["authorization"]
    expires = epoch(auth["validUntil"])
    authorized = epoch(auth["approvedAt"]) <= now and (expires is None or now < expires)
    monitor = result.get("usageMonitor", {})
    require(isinstance(monitor, dict), "Invalid usage monitor")
    seen = result.get("seenAnnouncementIds", [])
    require(isinstance(seen, list) and all(text(v) for v in seen), "Invalid event ledger")
    active = monitor.get("mode") == "top"
    decision, reason = "no_announcement", "No new public event supplied"
    if active:
        monitor, reason = observe(monitor, current)
        if monitor["mode"] == "top" and (
            not authorized or fingerprint(profile) != monitor.get("authorizationFingerprint")
        ):
            monitor.update(
                mode="normal",
                stoppedAt=current["observedAt"],
                stopReason="authorization_expired_or_changed",
            )
            reason = monitor["stopReason"]
        result["usageMonitor"] = monitor
        decision = "continue_window" if monitor["mode"] == "top" else "stop_new_work"
    stopped_reason = reason if decision == "stop_new_work" else None
    event_status = "absent"
    if event is not None:
        try:
            public = announcement(profile, event, now)
        except ValueError as error:
            event_status = str(error)
            if not active:
                decision, reason = "announcement_rejected", event_status
        else:
            seen = result.setdefault("seenAnnouncementIds", [])
            if public["id"] in seen:
                event_status = "duplicate"
                if not active:
                    decision, reason = "duplicate_announcement", "Event already handled"
            elif monitor.get("mode") == "top":
                seen.append(public["id"])
                event_status = "recorded_without_extending_window"
            elif (
                not authorized
                or not auth["conditionalStart"]
                or (
                    public["mechanism"] == "unspecified"
                    and not (
                        auth.get("allowUnspecifiedUpcoming", False)
                        and public["announcementStatus"] == "upcoming"
                    )
                )
            ):
                seen.append(public["id"])
                decision, reason = (
                    "advisory_only",
                    "No applicable conditional authority or mechanism",
                )
            elif (
                public["mechanism"] in {"automatic_restoration", "mixed"}
                and public["announcementStatus"] == "applied"
            ):
                seen.append(public["id"])
                decision, reason = (
                    "advisory_only",
                    "Automatic restoration announced as applied; "
                    "verify the account without starting",
                )
            elif (
                monitor.get("mode") == "normal"
                and monitor.get("stopReason")
                in {
                    "weekly_quota_replenished_before_expected_reset",
                    "weekly_quota_replenished",
                }
                and public["publishedAt"] <= epoch(monitor.get("stoppedAt"))
            ):
                seen.append(public["id"])
                decision, reason = (
                    "advisory_only",
                    "Weekly replenishment already confirmed after this publication",
                )
            elif epoch(monitor.get("startedAt")) is not None and public["publishedAt"] <= epoch(
                monitor["startedAt"]
            ):
                seen.append(public["id"])
                decision, reason = (
                    "advisory_only",
                    "Publication predates the latest work window; it cannot restart work",
                )
            elif not candidates:
                decision, reason = (
                    "preflight_blocked",
                    "No ready work with an available owner",
                )
            else:
                window = weekly(current)
                renewal = epoch(window.get("resetsAt")) if window else None
                quota_blocked = any(w["usedPercent"] >= 100 for w in current["windows"])
                if not window or quota_blocked:
                    decision, reason = (
                        "preflight_blocked",
                        "Fresh available weekly quota is required",
                    )
                elif profile["limits"]["stopOnScheduledWeeklyRenewal"] and (
                    renewal is None or renewal <= now
                ):
                    decision, reason = (
                        "preflight_blocked",
                        "A future weekly renewal time is required",
                    )
                else:
                    if monitor:
                        result.setdefault("completedWindows", []).append(
                            {
                                k: monitor.get(k)
                                for k in (
                                    "startedAt",
                                    "effectiveStopAt",
                                    "stoppedAt",
                                    "stopReason",
                                )
                            }
                        )
                    monitor = {
                        "mode": "top",
                        "startedAt": current["observedAt"],
                        "effectiveStopAt": min(
                            now + profile["limits"]["maximumHours"] * 3600,
                            expires if expires is not None else float("inf"),
                        ),
                        "baseline": current,
                        "last": current,
                        "authorizationFingerprint": fingerprint(profile),
                        "stopOnScheduledWeeklyRenewal": profile["limits"][
                            "stopOnScheduledWeeklyRenewal"
                        ],
                        "scheduledWeeklyStopAt": renewal,
                        "detectLowUsageRenewalShift": True,
                        "announcement": public,
                    }
                    result["usageMonitor"] = monitor
                    seen.append(public["id"])
                    decision, reason = (
                        "start_window",
                        "Previously authorized fresh reset announcement",
                    )
                    event_status = "consumed"
        if event_status == "absent":
            event_status = decision
    if stopped_reason is not None and decision != "start_window":
        decision, reason = "stop_new_work", stopped_reason
    monitor = result.get("usageMonitor", {})
    mode = monitor.get("mode", "normal")
    stop = stop_new_work_at(monitor)
    capacity_available = bool(weekly(current)) and all(
        w["usedPercent"] < 100 for w in current["windows"]
    )
    fresh = reason != "stale_observation"
    if decision == "continue_window" and not (capacity_available and fresh):
        decision = "wait_for_capacity"
    result["stopNewWorkAt"] = stop
    if now >= (epoch(result.get("lastUpdatedAt")) or now):
        result["lastUpdatedAt"] = current["observedAt"]
    return result, {
        "decision": decision,
        "reason": reason,
        "announcementStatus": event_status,
        "mode": mode,
        "stopNewWorkAt": stop,
        "nextWork": candidates if mode == "top" and capacity_available and fresh else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--event", type=Path)
    parser.add_argument("--observed-at", required=True)
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text())
        state = json.loads(args.state.read_text()) if args.state.exists() else {}
        event = json.loads(args.event.read_text()) if args.event else None
        current = snapshot(json.load(sys.stdin), args.observed_at)
        state, advice = preflight(profile, state, current, event)
        write_private(args.state, state)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Preflight refused: {error}\n")
    print(json.dumps(advice))


if __name__ == "__main__":
    main()

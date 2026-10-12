"""Check a human-approved Top Mode profile: is it valid, what is ready, what may an action do."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from usage_monitor import epoch, number

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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
    # Older profiles may still carry announcement fields; they are ignored.
    backlog_sources = profile["sources"].get("backlog")
    require(
        isinstance(backlog_sources, list)
        and backlog_sources
        and all(text(v) for v in backlog_sources),
        "Missing backlog sources",
    )
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
    hours = number(limits.get("maximumHours"))
    require(hours is not None and hours > 0, "Invalid limit: maximumHours")
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
    """Changes when anything the human approved changes; backlog progress does not."""
    approved = {key: value for key, value in profile.items() if key != "backlog"}
    return hashlib.sha256(json.dumps(approved, sort_keys=True).encode()).hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--project", help="With --action: the project the action is for")
    parser.add_argument("--action", choices=sorted(ACTIONS), help="Also print allowed, ask or deny")
    args = parser.parse_args()
    if bool(args.project) != bool(args.action):
        parser.error("--project and --action go together")
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        validate_profile(profile)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Profile refused: {error}\n")
    auth, now = profile["authorization"], time.time()
    expires = epoch(auth["validUntil"])
    result = {
        "authorizationActive": epoch(auth["approvedAt"]) <= now
        and (expires is None or now < expires),
        "readyWork": ready_work(profile),
        "fingerprint": fingerprint(profile),
    }
    if args.action:
        result["decision"] = action_decision(profile, args.project, args.action)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

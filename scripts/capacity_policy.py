"""Check a human-approved Quota Coach profile: is it valid, and what may an action do."""

import argparse
import hashlib
import json
import time
from pathlib import Path, PurePath

from usage_monitor import epoch, number

CAREFUL = {
    "read": "allowed",
    "edit": "allowed",
    "checks": "allowed",
    "commit": "allowed",
    "publish_pr": "ask",
    "review": "ask",
    "merge": "ask",
    "install": "ask",
    "access": "ask",
    "finance": "deny",
    "destruction": "deny",
    "redeem_reset": "ask",
}
LEVELS = {
    "careful": CAREFUL,
    "balanced": {**CAREFUL, "publish_pr": "allowed", "review": "allowed"},
    "autonomous": {**CAREFUL, "publish_pr": "allowed", "review": "allowed", "merge": "allowed"},
}
ACTIONS = set(CAREFUL)
DECISIONS = {"allowed", "ask", "deny"}
GITHUB = {"github-issues", "github-prs", "github-alerts"}
TIERS = {"repeatable", "ordinary", "difficult"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def fields(section: dict, required: set, optional: set, where: str) -> None:
    missing, unknown = required - set(section), set(section) - required - optional
    require(not missing, f"Missing in {where}: {', '.join(sorted(missing))}")
    require(not unknown, f"Unknown in {where}: {', '.join(sorted(unknown))}")


def absolute(value) -> bool:
    return text(value) and PurePath(value).is_absolute()


def work_source(value) -> bool:
    """A GitHub source, or a file inside the project such as ROADMAP.md."""
    if not text(value):
        return False
    if value.startswith("github-"):
        return value in GITHUB
    path = PurePath(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_profile(profile: dict) -> None:
    require(isinstance(profile, dict), "The profile must be a JSON object")
    require(
        not (type(profile.get("schemaVersion")) is int and profile["schemaVersion"] == 1),
        "This setup uses the old format (schemaVersion 1). Set it up again; "
        "the agent can carry over its projects, exclusions and limits",
    )
    require(
        type(profile.get("schemaVersion")) is int and profile["schemaVersion"] == 2,
        "Unsupported profile version",
    )
    fields(
        profile,
        {"schemaVersion", "authorization", "level", "limits", "projects"},
        {"actions", "excluded", "models"},
        "the profile",
    )
    auth = profile["authorization"]
    require(isinstance(auth, dict), "Invalid authorization")
    fields(auth, {"source", "approvedAt", "validUntil"}, set(), "authorization")
    approved, expires = epoch(auth["approvedAt"]), epoch(auth["validUntil"])
    require(
        text(auth["source"])
        and approved is not None
        and (auth["validUntil"] is None or (expires is not None and approved < expires)),
        "Human authorization needs a source, an approval time and an explicit expiry or null",
    )
    require(
        isinstance(profile["level"], str) and profile["level"] in LEVELS,
        "The level must be careful, balanced or autonomous",
    )
    actions = profile.get("actions", {})
    require(
        isinstance(actions, dict)
        and all(k in ACTIONS and isinstance(v, str) and v in DECISIONS for k, v in actions.items()),
        "Invalid action exception",
    )
    require(
        actions.get("redeem_reset") != "allowed",
        "Reset redemption always requires current human confirmation",
    )
    limits = profile["limits"]
    require(isinstance(limits, dict), "Invalid limits")
    fields(
        limits,
        {"maximumHours", "maximumActiveThreads", "stopOnScheduledWeeklyRenewal"},
        set(),
        "limits",
    )
    hours = number(limits["maximumHours"])
    require(hours is not None and hours > 0, "Invalid limit: maximumHours")
    require(
        type(limits["maximumActiveThreads"]) is int and limits["maximumActiveThreads"] > 0,
        "Invalid active-thread limit",
    )
    require(
        type(limits["stopOnScheduledWeeklyRenewal"]) is bool,
        "The scheduled-weekly-renewal policy must be explicit",
    )
    excluded = profile.get("excluded", [])
    require(
        isinstance(excluded, list) and all(absolute(p) for p in excluded),
        "Exclusions must be absolute folder paths",
    )
    projects = profile["projects"]
    require(isinstance(projects, dict) and projects, "At least one project is required")
    for name, project in projects.items():
        where = f"project {name}"
        require(text(name) and isinstance(project, dict), f"Invalid {where}")
        fields(project, {"label", "path", "work", "priority"}, {"notes"}, where)
        require(text(project["label"]), f"{where} needs a label")
        require(absolute(project["path"]), f"{where} needs an absolute path")
        path = PurePath(project["path"])
        require(
            not any(PurePath(p) == path or PurePath(p) in path.parents for p in excluded),
            f"{where} is inside an excluded folder",
        )
        require(
            isinstance(project["work"], list)
            and project["work"]
            and all(work_source(s) for s in project["work"]),
            f"{where} needs work sources: GitHub ones or files inside the project",
        )
        require(
            type(project["priority"]) is int and project["priority"] >= 0,
            f"{where} needs a priority (0 or more, lower first)",
        )
        require(text(project.get("notes", "-")), f"{where} has empty notes")
    models = profile.get("models", {})
    require(
        isinstance(models, dict)
        and all(
            text(agent)
            and isinstance(tiers, dict)
            and tiers
            and all(t in TIERS and text(m) for t, m in tiers.items())
            for agent, tiers in models.items()
        ),
        "Models are optional: per agent, repeatable, ordinary or difficult model names",
    )


def effective_actions(profile: dict) -> dict:
    """The level's decisions with the user's exceptions on top."""
    return {**LEVELS[profile["level"]], **profile.get("actions", {})}


def action_decision(profile: dict, project: str, action: str) -> str:
    """A policy ceiling, never a replacement for action-specific consent."""
    validate_profile(profile)
    if project not in profile["projects"]:
        return "deny"
    return effective_actions(profile).get(action, "deny")


def fingerprint(profile: dict) -> str:
    """Changes whenever anything the human approved changes."""
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:16]


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
        "level": profile["level"],
        "actions": effective_actions(profile),
        "fingerprint": fingerprint(profile),
    }
    if args.action:
        result["decision"] = action_decision(profile, args.project, args.action)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

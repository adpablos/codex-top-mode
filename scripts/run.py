"""Keep a private journal of each Top Mode run and answer from it.

`start` fixes the deadline and takes the quota baseline, `task` and `session`
record the work, `status` says what is going on and whether to stop, `stop`
ends new assignments, and `close` ends the run and writes the report's skeleton.
Never assigns work by itself.
"""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from capacity_policy import authorization_active, fingerprint, require, validate_profile
from profile_binding import locate, private_folder, private_path
from usage_monitor import epoch, weekly
from usage_report import (
    agent_home,
    claude_tokens,
    codex_tokens,
    iso,
    latest_quota,
    markdown,
)

AGENTS = ("codex", "claude")
SOURCES = {"codex_session_log": "Codex local logs", "codexbar": "CodexBar"}
STATUSES = ("planned", "in_progress", "done", "blocked")
TASK_FIELDS = ("project", "objective", "doneWhen", "owner")
ROLES = ("coordinator", "worker", "reviewer")
# Why a run stopped, as the report says it.
REASONS = {
    "deadline": "the deadline arrived",
    "user": "you asked to stop",
    "nothing_ready": "no ready work was left",
    "profile_changed": "the setup changed",
    "authorization_ended": "the approval ended",
    "weekly_renewal": "the weekly allowance renewed",
}
# A different renewal time than this means another weekly window.
SAME_WINDOW_SECONDS = 600


def write_text(path: Path, text: str) -> Path:
    """Atomically write an owner-only file in an owner-only folder outside Git."""
    path = private_path(path, existing=False)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        require(not path.parent.stat().st_mode & 0o077, "Use an owner-only private folder")
    handle, name = tempfile.mkstemp(prefix=".run-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return path


def load(path: Path) -> dict:
    if not path.exists() and not path.is_symlink():
        return {"schemaVersion": 1, "runs": []}
    data = json.loads(private_path(path, existing=True).read_text(encoding="utf-8"))
    require(
        isinstance(data, dict)
        and data.get("schemaVersion") == 1
        and isinstance(data.get("runs"), list),
        "Unsupported run journal",
    )
    return data


def save(path: Path, data: dict) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def current(data: dict):
    """The open run, if any: only the latest can be open."""
    runs = data["runs"]
    return runs[-1] if runs and not runs[-1].get("endedAt") else None


def readings(codex_home: Path) -> dict:
    """The best reading per agent: CodexBar, then Codex's own logs."""
    found = {agent: latest_quota(agent, codex_home) for agent in AGENTS}
    return {
        agent: {**r, "observedAt": iso(epoch(r["observedAt"]))} if r else None
        for agent, r in found.items()
    }


def start(data: dict, profile: dict, hours: float, agents: list, found: dict, now: float):
    require(current(data) is None, "A run is still open; stop and close it first")
    require(hours > 0, "Give the run a positive number of hours")
    agents = list(dict.fromkeys(agents))
    require(authorization_active(profile, now), "The setup's approval is not active now")
    for agent in agents:
        week = weekly(found[agent]) if found[agent] else None
        require(
            not week or week["usedPercent"] < 100 or (week["resetsAt"] or now + 1) <= now,
            f"{agent} has used up its weekly allowance; wait for it to renew",
        )
    limits, auth = profile["limits"], profile["authorization"]
    candidates = [(now + hours * 3600, None), (now + limits["maximumHours"] * 3600, "maximumHours")]
    if auth["validUntil"] is not None:
        candidates.append((epoch(auth["validUntil"]), "validUntil"))
    unknown = []
    for agent in agents if limits["stopOnScheduledWeeklyRenewal"] else ():
        week = weekly(found[agent]) if found[agent] else None
        if week and week["resetsAt"] and week["resetsAt"] > now:
            candidates.append((week["resetsAt"], f"{agent} weekly renewal"))
        else:
            unknown.append(f"{agent}: renewal time unknown, so the run could not stop at it")
    deadline, capped = min(candidates, key=lambda candidate: candidate[0])
    run = {
        "startedAt": iso(now),
        "requestedHours": hours,
        "deadline": iso(deadline),
        "cappedBy": capped,
        "agents": agents,
        "level": profile["level"],
        "fingerprint": fingerprint(profile),
        "projects": {name: p["label"] for name, p in profile["projects"].items()},
        "maximumActiveThreads": limits["maximumActiveThreads"],
        "quotaBefore": {agent: found[agent] for agent in agents},
        "unknown": unknown,
        "tasks": [],
        "sessions": [],
    }
    data["runs"].append(run)
    return run


def record_task(run: dict, task_id: str, fields: dict, now: float) -> dict:
    """Add a task or record its progress; a refused change leaves the run as it was."""
    index = next((i for i, t in enumerate(run["tasks"]) if t["id"] == task_id), None)
    task = None if index is None else run["tasks"][index]
    status = fields["status"]
    if "stoppedAt" in run:
        require(
            task is not None
            and status in (task["status"], "done", "blocked")
            and all(fields.get(k) in (None, "", task.get(k)) for k in TASK_FIELDS),
            "The run stopped: record only how existing tasks ended, as done or blocked",
        )
    if task is None:
        require(
            all(fields.get(k) for k in TASK_FIELDS),
            "A new task needs --project, --objective, --done-when and --owner",
        )
    require(not fields.get("needsYou") or status == "blocked", "--needs-you goes with blocked")
    updated = {**(task or {"id": task_id, "status": None, "events": []})}
    updated.update({k: v for k, v in fields.items() if v and k != "status"})
    require(updated["project"] in run["projects"], "Unknown project: add it to the setup first")
    if status != updated["status"]:
        # Reaching done or blocked again needs fresh evidence or a fresh blocker.
        require(status != "done" or fields.get("evidence"), "Say how it was verified: --evidence")
        require(status != "blocked" or fields.get("blocker"), "Say what blocks it: --blocker")
        if status != "done":
            updated.pop("evidence", None)
        if status != "blocked":
            updated.pop("blocker", None)
            updated.pop("needsYou", None)
        updated["status"] = status
        updated["events"] = [*updated["events"], {"at": iso(now), "status": status}]
    if status == "blocked" and fields.get("blocker"):
        # A new blocker says again whether it waits on the user.
        updated.pop("needsYou", None)
        updated.update({"needsYou": True} if fields.get("needsYou") else {})
    # Replace the task whole, so the fields dropped above leave the journal too.
    if index is None:
        run["tasks"].append(updated)
    else:
        run["tasks"][index] = updated
    return updated


def record_session(run: dict, session_id, agent: str, role: str, ended: bool, now: float):
    require(
        agent in run["agents"],
        f"This run does not track {agent}'s quota; name every agent it spends at start",
    )
    if not session_id:
        # No ID the host shows: give one, which the caller reuses for --ended.
        taken = {s["id"] for s in run["sessions"]}
        session_id = next(
            f"{agent}-{role}-{n}"
            for n in range(1, len(taken) + 2)
            if f"{agent}-{role}-{n}" not in taken
        )
    session = next((s for s in run["sessions"] if s["id"] == session_id), None)
    require(session or "stoppedAt" not in run, "The run stopped: start no new sessions")
    require(
        session is None or (session["agent"], session["role"]) == (agent, role),
        "That ID is another session's: give a different one",
    )
    if session is None:
        session = {"id": session_id, "agent": agent, "role": role, "startedAt": iso(now)}
        session["endedAt"] = None
        run["sessions"].append(session)
    if ended and not session["endedAt"]:
        session["endedAt"] = iso(now)
    return session


def owner(run: dict, name: str) -> str:
    """Who owns a task, never as a session ID."""
    session = next((s for s in run["sessions"] if s["id"] == name), None)
    return f"{session['agent']} {session['role']} session" if session else name


def task_view(run: dict, task: dict) -> dict:
    keys = ("id", "project", "objective", "evidence", "blocker", "needsYou")
    view = {k: task[k] for k in keys if k in task}
    return {**view, "owner": owner(run, task["owner"])}


def quota_now(run: dict, found: dict, now: float) -> dict:
    result = {}
    for agent in run["agents"]:
        reading = found.get(agent)
        week = weekly(reading) if reading else None
        result[agent] = reading and {
            "weeklyUsedPercent": week["usedPercent"] if week else None,
            "observedAt": reading["observedAt"],
            "minutesOld": round((now - epoch(reading["observedAt"])) / 60),
        }
    return result


def status(run: dict, profile, found: dict, now: float) -> dict:
    """What is going on, and whether to stop assigning work."""
    reasons = []
    if now >= epoch(run["deadline"]):
        reasons.append("deadline")
    if profile is None or fingerprint(profile) != run["fingerprint"]:
        reasons.append("profile_changed")
    elif not authorization_active(profile, now):
        reasons.append("authorization_ended")
    # A journal from an older version may hold its renewal observer's final word.
    legacy = run.get("usageMonitor") or {}
    if (
        legacy.get("mode") == "normal"
        and legacy.get("stopReason") != "authorized_time_window_ended"
    ):
        reasons.append("weekly_renewal")
    active = [s for s in run["sessions"] if not s["endedAt"] and s["role"] != "coordinator"]
    working = [t for t in run["tasks"] if t["status"] == "in_progress"]
    # The coordinator is one thread; each task in progress counts, even two of one session.
    busy = 1 + max(len(active), len(working))
    return {
        "active": True,
        "startedAt": run["startedAt"],
        "deadline": run["deadline"],
        "minutesLeft": max(0, round((epoch(run["deadline"]) - now) / 60)),
        "stoppedAt": run.get("stoppedAt"),
        "stopNow": bool(reasons) or "stoppedAt" in run,
        "stopReasons": reasons,
        "tasks": {
            s: [task_view(run, t) for t in run["tasks"] if t["status"] == s] for s in STATUSES
        },
        "waitingOnYou": [task_view(run, t) for t in run["tasks"] if t.get("needsYou")],
        "activeSessions": len(active),
        "freeThreads": max(0, run["maximumActiveThreads"] - busy),
        "quota": quota_now(run, found, now),
    }


def stop(run: dict, reason: str, now: float) -> dict:
    """No new assignments from now on; the run stays open to record checkpoints."""
    require("stoppedAt" not in run, "The run already stopped; close it with `run.py close`")
    require(
        reason != "deadline" or now >= epoch(run["deadline"]) - 60,
        "The deadline has not arrived; give the real reason",
    )
    run.update(stoppedAt=iso(now), stopReason=reason)
    return run


def close(run: dict, found: dict, now: float) -> dict:
    require("stoppedAt" in run, "Stop the run first with `run.py stop`")
    run["endedAt"] = iso(now)
    run["quotaAfter"] = {agent: found.get(agent) for agent in run["agents"]}
    return run


def sentence(text: str) -> str:
    return text if text.endswith((".", "?", "!")) else f"{text}."


def clock(stamp) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(epoch(stamp)))


def quota_row(agent: str, before, after) -> str:
    if not before and not after:
        hint = "; install CodexBar to see it" if agent == "claude" else ""
        return f"unknown: no reading{hint}"

    def one(reading):
        if not reading:
            return "unknown"
        week = weekly(reading)
        used = f"{week['usedPercent']:g}% used" if week else "weekly window unknown"
        return f"{used} at {clock(reading['observedAt'])}"

    # A run journal from an older version can name a source no longer read.
    sources = sorted({SOURCES.get(r["source"], r["source"]) for r in (before, after) if r})
    text = f"{one(before)} → {one(after)} ({', '.join(sources)})."
    weeks = [weekly(r) if r else None for r in (before, after)]
    if not all(weeks):
        return text
    renewals = [w["resetsAt"] for w in weeks]
    if None not in renewals and abs(renewals[0] - renewals[1]) > SAME_WINDOW_SECONDS:
        return text + " The allowance renewed in between, so the difference is not this run's use."
    renews = f" Renews {clock(renewals[1])}." if renewals[1] else ""
    return text + " Includes anything else on the account meanwhile." + renews


def report(run: dict, tokens: str) -> str:
    out = [
        f"# Top Mode report, {clock(run['startedAt'])}",
        "",
        "<!-- Skeleton from the run journal. Rewrite it in the user's language: first what",
        "waits on the user, each with your recommendation; then for each project, before",
        "and verified after, why it matters, what is pending and who acts next. Keep the",
        "facts in the tables. -->",
        "",
    ]
    waiting = [t for t in run["tasks"] if t.get("needsYou")]
    if waiting:
        out += ["## Waiting on you", ""]
        for t in waiting:
            label = run["projects"][t["project"]]
            out.append(f"- **{label}:** {sentence(t['objective'])} {sentence(t['blocker'])}")
        out.append("")
    out += ["## What changed", ""]
    for project, label in run["projects"].items():
        tasks = [t for t in run["tasks"] if t["project"] == project]
        if tasks:
            out.append(f"**{label}**")
        for t in tasks:
            who = "you" if t.get("needsYou") else owner(run, t["owner"])
            if t["status"] == "done":
                out.append(
                    f"- Done: {sentence(t['objective'])} Verified: {sentence(t['evidence'])}"
                )
            elif t["status"] == "blocked":
                out.append(
                    f"- Blocked: {sentence(t['objective'])} {sentence(t['blocker'])} Next: {who}."
                )
            else:
                state = t["status"].replace("_", " ")
                out.append(f"- Not finished ({state}): {sentence(t['objective'])} Next: {who}.")
        if tasks:
            out.append("")
    if not run["tasks"]:
        out += ["No tasks were recorded.", ""]
    capped = f", capped by {run['cappedBy']}" if run["cappedBy"] else ""
    out += [
        "## The run",
        "",
        "| | |",
        "| --- | --- |",
        f"| Started | {clock(run['startedAt'])}, for {run['requestedHours']:g} h |",
        f"| Deadline | {clock(run['deadline'])}{capped} |",
        f"| Stopped | {clock(run['stoppedAt'])}: {REASONS[run['stopReason']]} |",
        f"| Closed | {clock(run['endedAt'])}, after collecting checkpoints |",
        f"| Level | {run['level']} |",
    ]
    for agent in run["agents"]:
        before, after = run["quotaBefore"].get(agent), run["quotaAfter"].get(agent)
        out.append(f"| Weekly quota, {agent} | {quota_row(agent, before, after)} |")
    groups = {}
    for s in run["sessions"]:
        counts = groups.setdefault(f"{s['agent']} {s['role']}", [0, 0])
        counts[0] += 1
        counts[1] += bool(s["endedAt"])
    sessions = "; ".join(f"{k}: {v[0]} started, {v[1]} finished" for k, v in groups.items())
    if not any(s["role"] == "coordinator" for s in run["sessions"]):
        sessions = f"{sessions or 'none started'} (plus this coordinator)"
    out.append(f"| Sessions | {sessions} |")
    if (run.get("usageMonitor") or {}).get("bankedResetObserved"):  # older versions only
        out.append("| Saved resets | A new one appeared during the run; it did not extend it. |")
    out += [
        "",
        "## Tokens",
        "",
        tokens,
        "",
        "Every session on this machine in that interval counts, including work outside",
        "the run. Token counts are not your bill.",
    ]
    if run["unknown"]:
        out += ["", "## Unknown", ""] + [f"- {item}" for item in run["unknown"]]
    return "\n".join(out) + "\n"


def report_path(folder: Path, since: float) -> Path:
    """A new file per run, even for two runs started in the same second."""
    stem = time.strftime("%Y-%m-%d-%H%M%S", time.gmtime(since))
    path, n = folder / f"{stem}.md", 1
    while path.exists() or path.is_symlink():
        n += 1
        path = folder / f"{stem}-{n}.md"
    return path


def load_profile(args) -> dict:
    path = args.profile or Path(locate(args.private / "binding.json")["profilePath"])
    profile = json.loads(path.read_text(encoding="utf-8"))
    validate_profile(profile)
    return profile


def main() -> None:
    private = argparse.ArgumentParser(add_help=False)
    private.add_argument("--private", type=Path, help=argparse.SUPPRESS)
    sources = argparse.ArgumentParser(add_help=False, parents=[private])
    sources.add_argument("--profile", type=Path, help="Default: the saved setup")
    sources.add_argument("--codex-home", type=Path, default=agent_home("CODEX_HOME", ".codex"))
    sources.add_argument(
        "--claude-home", type=Path, default=agent_home("CLAUDE_CONFIG_DIR", ".claude")
    )
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start", parents=[sources], help="Start a run")
    begin.add_argument("--hours", type=float, required=True)
    begin.add_argument(
        "--agents", nargs="+", choices=AGENTS, required=True, help="Whose quota the run spends"
    )
    work = commands.add_parser("task", parents=[private], help="Record a task or its progress")
    work.add_argument("id")
    work.add_argument("--status", choices=STATUSES, required=True)
    for name in ("project", "objective", "done-when", "owner", "evidence", "blocker"):
        work.add_argument(f"--{name}")
    work.add_argument(
        "--needs-you", action="store_true", help="Blocked on the user's decision or action"
    )
    one = commands.add_parser("session", parents=[private], help="Record a session the run uses")
    one.add_argument("id", nargs="?", help="The host's session ID; default: a new one")
    one.add_argument("--agent", choices=AGENTS, required=True)
    one.add_argument("--role", choices=ROLES, default="worker")
    one.add_argument("--ended", action="store_true")
    commands.add_parser("status", parents=[sources], help="Where the run stands; stop or not")
    end = commands.add_parser("stop", parents=[private], help="Stop assigning work, say why")
    end.add_argument("--reason", choices=REASONS, required=True)
    commands.add_parser("close", parents=[sources], help="End the run, write the report")
    args = parser.parse_args()
    args.private = args.private or private_folder()
    now = time.time()
    try:
        journal = args.private / "runs.json"
        data = load(journal)
        run = current(data)
        if args.command == "status" and run is None:
            keys = ("startedAt", "endedAt", "stopReason", "report")
            last = {k: data["runs"][-1].get(k) for k in keys} if data["runs"] else None
            print(json.dumps({"active": False, "lastRun": last}))
            return
        require(args.command == "start" or run is not None, "No run is open")
        if args.command in ("start", "status", "close"):
            found = readings(args.codex_home)
        if args.command == "start":
            run = start(data, load_profile(args), args.hours, args.agents, found, now)
            result = {k: run[k] for k in ("startedAt", "deadline", "cappedBy", "level", "unknown")}
        elif args.command == "task":
            fields = {
                "status": args.status,
                "project": args.project,
                "objective": args.objective,
                "doneWhen": args.done_when,
                "owner": args.owner,
                "evidence": args.evidence,
                "blocker": args.blocker,
                "needsYou": args.needs_you,
            }
            task = record_task(run, args.id, fields, now)
            result = {**task, "owner": owner(run, task["owner"])}
        elif args.command == "session":
            session = record_session(run, args.id, args.agent, args.role, args.ended, now)
            # A host's ID stays private; one run.py gave is needed again for --ended.
            hidden = () if args.id is None else ("id",)
            result = {k: v for k, v in session.items() if k not in hidden}
        elif args.command == "status":
            try:
                profile = load_profile(args)
            except (OSError, ValueError):
                profile = None  # Missing or broken now: either way, not what was approved.
            result = status(run, profile, found, now)
        elif args.command == "stop":
            stop(run, args.reason, now)
            result = {"stoppedAt": run["stoppedAt"], "stopReason": args.reason}
        else:
            close(run, found, now)
            since = epoch(run["startedAt"])
            tokens = {
                "since": iso(since),
                "until": iso(now),
                "providers": [
                    codex_tokens(args.codex_home, since, now),
                    claude_tokens(args.claude_home, since, now),
                ],
            }
            path = report_path(args.private / "reports", since)
            write_text(path, report(run, markdown(tokens)))
            run["report"] = str(path)
            result = {"report": str(path), "stopReason": run["stopReason"]}
        save(journal, data)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result))


if __name__ == "__main__":
    main()

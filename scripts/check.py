"""One quiet check: is there spare capacity worth a Top Mode run?

Looks at every source available on this machine and prints one line per thing
worth telling the user. Prints nothing when there is nothing to say, so it can
run on a schedule. Never starts work.
"""

import argparse
import json
import time
from pathlib import Path

from profile_binding import private_path
from usage_monitor import write_private
from usage_report import advise, agent_home, codexbar_quota, file_quota, latest_quota

PRIVATE = Path.home() / ".codex-top-mode"
QUIET_SECONDS = 20 * 3600
# What to do when an agent has no reading, for --verbose.
NO_READING = {
    "Codex": "it appears once a Codex session reports its limits",
    "Claude": "install CodexBar (https://codexbar.app) to see it",
}


def saved(path):
    """A saved reading that carries its capture time; anything else counts as none."""
    try:
        return file_quota(path)
    except (OSError, ValueError):
        return None


def readings(codex_home, claude_status, quota_file):
    """(agent, reading or None) for each quota source."""
    if quota_file:
        return [("quota file", saved(quota_file))]
    claude = codexbar_quota("claude")
    if claude is None and claude_status.is_file():
        claude = saved(claude_status)
    return [("Codex", latest_quota("codex", codex_home)), ("Claude", claude)]


def quota_lines(agent, advice):
    """(key, message) pairs; the key identifies the same news across checks."""
    # A stale reading or a reached limit needs a fresh reading first, not a run.
    if advice["suggestion"] != "consider_top_mode":
        return []
    lines = []
    reasons = advice["reasons"]
    if "unused_weekly_quota_before_reset" in reasons:
        unused = round(100 - advice["weeklyUsedPercent"])
        lines.append(
            (
                f"{agent}:unused:{advice['weeklyResetsAt']}",
                f"{agent}: {unused}% of the weekly allowance is unused and it renews in "
                f"{advice['hoursToWeeklyReset']:g} h. Worth a Top Mode run.",
            )
        )
    if "saved_resets_expiring_soon" in reasons:
        dates = ", ".join(advice["expiringResets"])
        lines.append(
            (
                f"{agent}:expiring:{dates}",
                f"{agent}: saved resets expire soon ({dates}). Use or redeem them first.",
            )
        )
    return lines


def unseen(lines, path, now):
    """Drop news already told in the last day; remember what is told now."""
    try:
        told = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        told = {}
    told = {k: t for k, t in told.items() if isinstance(t, (int, float)) and now - t < 8 * 86400}
    fresh = [(key, line) for key, line in lines if now - told.get(key, 0) >= QUIET_SECONDS]
    if fresh:
        told.update({key: now for key, _ in fresh})
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(path, told)
    return [line for _, line in fresh]


def summary_line(agent, advice):
    if "no_quota_reading" in advice["reasons"]:
        hint = NO_READING.get(agent)
        return f"{agent}: no quota reading" + (f" ({hint})." if hint else ".")
    used = advice["weeklyUsedPercent"]
    week = "weekly allowance unknown" if used is None else f"{used:g}% of the weekly allowance used"
    if advice["hoursToWeeklyReset"] is not None:
        week += f", renews in {advice['hoursToWeeklyReset']:g} h"
    age = f"reading {advice['readingAgeHours']:g} h old"
    return f"{agent}: {week} ({age}). Suggestion: {advice['suggestion']}."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="Also print the full status")
    parser.add_argument("--json", action="store_true", help="The full status as JSON")
    parser.add_argument("--quota-file", type=Path, help="A saved reading with its capture time")
    parser.add_argument("--codex-home", type=Path, default=agent_home("CODEX_HOME", ".codex"))
    parser.add_argument("--private", type=Path, default=PRIVATE, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        # Nothing check reads or writes may sit in Git or behind a link.
        state, claude_status = (
            private_path(args.private / name, existing=False)
            for name in ("check-state.json", "claude-status.json")
        )
    except ValueError as error:
        parser.error(str(error))
    now = time.time()
    advice = [
        (agent, advise(reading, now))
        for agent, reading in readings(args.codex_home, claude_status, args.quota_file)
    ]
    news = [pair for agent, item in advice for pair in quota_lines(agent, item)]
    if args.json:
        lines = [line for _, line in news]
        print(json.dumps({"messages": lines, "quota": dict(advice)}, indent=2))
        return
    if args.verbose:
        lines = [summary_line(agent, item) for agent, item in advice]
        lines += [line for _, line in news]
    else:
        # Scheduled checks repeat; tell each piece of news at most once a day.
        lines = unseen(news, state, now)
    if lines:
        print("\n".join(lines))


if __name__ == "__main__":
    main()

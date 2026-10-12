"""Has the subscription plan been enough? Weekly windows rebuilt from quota readings.

Pure functions over the account's weekly readings, as
`usage_report.codex_weekly_readings()` returns them: (time, used percent,
renewal time, plan). Nothing here reads files.
"""

import statistics
import time

WEEK = 7 * 24 * 3600
# Readings of one window give its renewal time to within seconds.
SAME_WINDOW = 600
# A window that renews this long before its scheduled time renewed early.
EARLY = 3600
# Readings of two windows that interleave for longer than this, with at least
# this many readings each, come from two meters at once.
OVERLAP = 3600
INTERLEAVED = 5
WINDOWS = 8
MINIMUM = 4


def day(seconds):
    return time.strftime("%Y-%m-%d", time.gmtime(seconds))


def summarize(readings):
    """One window from its readings in time order.

    A plan change rescales the percentage to the new plan, so the jump is not
    use: the new plan's percentage already includes what was used before.
    """
    plan, peak, limit, steps, changed = None, 0.0, None, [], False
    for stamp, used, _, kind in readings:
        if kind and plan and kind != plan:
            changed, peak, limit = True, used, None
        plan = kind or plan
        if used > peak:
            steps.append((stamp, used - peak, plan))
            peak = used
        if used >= 100 and limit is None:
            limit = stamp
    return {
        "renewsAt": max(reading[2] for reading in readings),
        "firstSeen": readings[0][0],
        "lastSeen": readings[-1][0],
        "plan": plan,
        "planChanged": changed,
        "peakPercent": peak,
        "limitReachedAt": limit,
        "steps": steps,
        "times": [reading[0] for reading in readings],
    }


def parallel(one, other):
    """Two windows whose readings interleave for a while are two meters at once.

    One late reading of an old window after a renewal is not enough.
    """
    start = max(one["firstSeen"], other["firstSeen"])
    end = min(one["lastSeen"], other["lastSeen"])
    if end - start < OVERLAP:
        return False
    return all(sum(start <= t <= end for t in w["times"]) >= INTERLEAVED for w in (one, other))


def windows(readings, now):
    """The account's weekly windows in time order, and how many readings were left out.

    Some logs carry a second weekly meter at the same time: one that stays near
    0% while the account's window fills, or another account signed in on the
    same machine. When two windows run in parallel, the one that used more is
    kept (on a tie, the one with more readings, then the later one); the other
    is not a renewal.
    """
    groups = []
    for reading in sorted(readings, key=lambda reading: reading[2]):
        if groups and reading[2] - groups[-1][-1][2] <= SAME_WINDOW:
            groups[-1].append(reading)
        else:
            groups.append([reading])
    found = [summarize(sorted(group, key=lambda reading: reading[0])) for group in groups]

    def rank(window):
        # Renewal times differ between groups, so exactly one of two parallel windows wins.
        return window["peakPercent"], len(window["times"]), window["renewsAt"]

    # Best first: a window is left out only for a parallel window that is kept.
    kept = []
    for window in sorted(found, key=rank, reverse=True):
        if not any(parallel(window, other) for other in kept):
            kept.append(window)
    left_out = sum(len(window["times"]) for window in found) - sum(
        len(window["times"]) for window in kept
    )
    kept.sort(key=lambda window: window["firstSeen"])
    for window, following in zip(kept, [*kept[1:], None]):
        renewed = window["renewsAt"]
        if following:
            # A window starts a week before it renews.
            renewed = min(renewed, following["renewsAt"] - WEEK)
        window["renewedAt"] = renewed
        window["early"] = window["renewsAt"] - renewed > EARLY
        window["closed"] = following is not None or renewed <= now
    return kept, left_out


def current_stretch(found):
    """Closed windows since the latest plan change, and that plan."""
    if not found:
        return None, []
    plan, stretch = found[-1]["plan"], []
    for window in reversed(found):
        if window["plan"] != plan:
            break
        if window["closed"]:
            stretch.append(window)
        if window["planChanged"]:
            break
    return plan, stretch[::-1]


def without_resets(found, plan, now):
    """Replay the use on this plan through natural weeks, with no early renewal.

    A natural window starts with the first use after the previous one ended and
    lasts a week. Only weeks that have ended, or already reached the limit,
    count. Where the real window hit
    the limit, real demand was higher than what was used, so the replay is a
    lower bound for that week.
    """
    steps = []
    for window in reversed(found):
        own = [step for step in window["steps"] if step[2] == plan]
        steps = own + steps
        if window["plan"] != plan or window["planChanged"]:
            break
    limits = [w["limitReachedAt"] for w in found if w["limitReachedAt"] and w["plan"] == plan]
    weeks = []
    for stamp, points, _ in steps:
        if not weeks or stamp >= weeks[-1]["start"] + WEEK:
            weeks.append({"start": stamp, "usedPercent": 0.0, "limitReachedAt": None})
        week = weeks[-1]
        week["usedPercent"] += points
        if week["usedPercent"] >= 100 and week["limitReachedAt"] is None:
            week["limitReachedAt"] = stamp
    for week in weeks:
        week["atLeast"] = any(week["start"] <= t < week["start"] + WEEK for t in limits)
    return [w for w in weeks if w["start"] + WEEK <= now or w["limitReachedAt"] is not None]


def advise_plan(readings, now, count=WINDOWS):
    """Facts about the latest closed windows on the current plan, and a verdict."""
    found, left_out = windows(readings, now)
    plan, stretch = current_stretch(found)
    recent = stretch[-count:]
    weeks = without_resets(found, plan, now)[-count:]
    hits = [w for w in recent if w["limitReachedAt"]]
    short_weeks = [w for w in weeks if w["limitReachedAt"]]
    if len(recent) < MINIMUM:
        verdict = "not_enough_history"
    elif len(hits) * 4 > len(recent):
        verdict = "short"
    elif len(short_weeks) * 4 > len(weeks):
        verdict = "enough_thanks_to_early_renewals"
    else:
        verdict = "enough"
    return {
        "plan": plan,
        "historySince": day(min(r[0] for r in readings)) if readings else None,
        "windows": [
            {
                "start": day(w["renewsAt"] - WEEK),
                "renewed": day(w["renewedAt"]),
                "renewedEarly": w["early"],
                "planChanged": w["planChanged"],
                "peakPercent": round(w["peakPercent"]),
                "limitReached": day(w["limitReachedAt"]) if w["limitReachedAt"] else None,
            }
            for w in recent
        ],
        "medianPeakPercent": round(statistics.median(w["peakPercent"] for w in recent))
        if recent
        else None,
        "withoutEarlyRenewals": [
            {
                "start": day(w["start"]),
                "usedPercent": round(w["usedPercent"]),
                "reachedLimit": w["limitReachedAt"] is not None,
                "atLeast": w["atLeast"],
            }
            for w in weeks
        ],
        "verdict": verdict,
        "parallelReadingsLeftOut": left_out,
        # Top Mode runs are not recorded yet, so their use cannot be told apart.
        "includesTopModeRuns": True,
    }


VERDICTS = {
    "short": "short. You reach the limit in more than 1 of every 4 weeks.",
    "enough_thanks_to_early_renewals": (
        "enough, thanks to early renewals. Without them you would reach the limit "
        "in more than 1 of every 4 weeks, and early renewals are not guaranteed."
    ),
    "enough": "enough.",
}


def markdown(advice):
    """A short plain summary; the agent explains it in the user's words."""
    plan, recent = advice["plan"], advice["windows"]
    if not recent:
        if advice["historySince"] is None:
            return "Codex: no weekly quota readings in the local logs yet."
        return (
            f"Codex: no closed weekly window on the current plan yet (readings since "
            f"{advice['historySince']}). A verdict needs {MINIMUM}."
        )
    out = [
        f'Codex weekly allowance, plan "{plan or "unknown"}": last {len(recent)} closed '
        f"windows ({recent[0]['start']} to {recent[-1]['renewed']}).",
        "- Peak use per window: "
        + ", ".join(str(w["peakPercent"]) for w in recent)
        + f" % (median {advice['medianPeakPercent']} %).",
    ]
    hits = [w["limitReached"] for w in recent if w["limitReached"]]
    out.append(
        f"- Reached the limit in {len(hits)} of {len(recent)}"
        + (f", the last on {hits[-1]}." if hits else ".")
    )
    early = sum(w["renewedEarly"] for w in recent)
    out.append(
        f"- Renewed early in {early} of {len(recent)} (an announced or saved reset, "
        "or a plan change)."
    )
    weeks = advice["withoutEarlyRenewals"]
    if weeks:
        short = [w for w in weeks if w["reachedLimit"]]
        most = max(weeks, key=lambda w: w["usedPercent"])
        out.append(
            f"- Without early renewals, the same use would have reached the limit in "
            f"{len(short)} of {len(weeks)} weeks (most: "
            f"{'at least ' if most['atLeast'] else ''}{most['usedPercent']} %, "
            f"week from {most['start']})."
        )
    out.append("- Includes Top Mode runs: they cannot be told apart from your own use yet.")
    if advice["parallelReadingsLeftOut"]:
        out.append(
            f"- Left out {advice['parallelReadingsLeftOut']} readings from a second weekly meter "
            "that ran at the same time (another account on this machine, or a meter that "
            "stays near 0 %)."
        )
    if advice.get("compressedLogs"):
        out.append(
            f"- {advice['compressedLogs']} compressed logs were not read, so the history "
            "may be shorter than it looks."
        )
    if advice["verdict"] == "not_enough_history":
        out.append(
            f"Not enough history for a verdict: {len(recent)} closed windows on this plan, "
            f"{MINIMUM} needed."
        )
    else:
        out.append("Verdict: " + VERDICTS[advice["verdict"]])
    return "\n".join(out)

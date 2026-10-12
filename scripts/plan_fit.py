"""Has the subscription plan been enough? Weekly windows rebuilt from quota readings.

Pure functions over the account's weekly readings, as
`usage_report.codex_weekly_readings()` returns them: (time, used percent,
renewal time, plan), and over the plans file (references/plans.json) for the
comparison with other plans. Nothing here reads files.
"""

import statistics
import time

from usage_monitor import epoch

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
# Plan sizes and prices older than this may have changed.
STALE_DAYS = 60
# A change to the current plan's size this close is worth a warning.
SOON = 30 * 24 * 3600
# A cheaper plan is suggested only if every window and week stays below this.
ROOM = 80


def day(seconds):
    return time.strftime("%Y-%m-%d", time.gmtime(seconds))


def summarize(readings, size=None):
    """One window from its readings in time order.

    A plan change rescales the percentage to the new plan, and so does a change
    of the plan's size when `size(plan, time)` gives it, so the jump is not use:
    the new percentage already includes what was used before.
    """
    plan, scale, peak, limit, steps, changed = None, None, 0.0, None, [], False
    for stamp, used, _, kind in readings:
        if kind and plan and kind != plan:
            changed = True
        plan = kind or plan
        rescaled = (plan, size(plan, stamp) if size else None)
        if scale and scale[0] and rescaled != scale:
            peak, limit = used, None
        scale = rescaled
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
        "readings": readings,
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


def windows(readings, now, size=None):
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
    found = [summarize(sorted(group, key=lambda reading: reading[0]), size) for group in groups]

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
    lasts a week; `ended` tells whether it has. Where the real window hit the
    limit, real demand was higher than what was used, so the replay is a lower
    bound for that week.
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
            weeks.append({"start": stamp, "usedPercent": 0.0, "limitReachedAt": None, "steps": []})
        week = weeks[-1]
        week["steps"].append((stamp, points, plan))
        week["usedPercent"] += points
        if week["usedPercent"] >= 100 and week["limitReachedAt"] is None:
            week["limitReachedAt"] = stamp
    for week in weeks:
        week["atLeast"] = any(week["start"] <= t < week["start"] + WEEK for t in limits)
        week["ended"] = week["start"] + WEEK <= now
    return weeks


def judge(windows_count, windows_at_limit, weeks_count, weeks_at_limit):
    if windows_count < MINIMUM:
        return "not_enough_history"
    if windows_at_limit * 4 > windows_count:
        return "short"
    if weeks_at_limit * 4 > weeks_count:
        return "enough_thanks_to_early_renewals"
    return "enough"


def times_plus(plan, when, grandfathered=False):
    """How much use the plan includes at a time, as a multiple of Plus; None if unknown.

    A grandfathered subscriber keeps the size the plan had before a change
    until the date the plans file gives.
    """
    kept = plan.get("grandfathered") if grandfathered else None
    if kept and when < epoch(kept["previousUntil"]):
        when = min(when, epoch(kept["activeUntil"]) - 1)
    value = None
    for period in plan.get("timesPlus") or []:
        if period["from"] is None or epoch(period["from"]) <= when:
            value = period["value"]
    return value


def grandfathered(plan, readings):
    """Readings on this plan during the eligibility period mean it was active then."""
    kept = plan.get("grandfathered")
    if not kept:
        return False
    start, end = epoch(kept["activeFrom"]), epoch(kept["activeUntil"])
    return any(r[3] == plan["planType"] and start <= r[0] < end for r in readings)


def sizing(plans, found):
    """Plans by type, the grandfathered ones, and each plan's size at a time.

    Grandfathering is inferred from the account's own windows only, not from a
    parallel meter that may belong to another account.
    """
    by_type = {p["planType"]: p for p in plans["plans"] if p.get("planType")}
    own = [reading for window in found for reading in window["readings"]]
    kept = {kind for kind, p in by_type.items() if grandfathered(p, own)}

    def size(kind, when):
        known = by_type.get(kind)
        return times_plus(known, when, kind in kept) if known else None

    return by_type, kept, size


def plus_weeks(steps, size, fallback):
    """Use in whole weeks of Plus, or None when a plan's size is unknown."""
    total = 0.0
    for stamp, points, kind in steps:
        times = size(kind or fallback, stamp)
        if times is None:
            return None
        total += points / 100 * times
    return total


def fit(demand, weeks, times):
    """The same use against a plan that includes `times` Plus.

    `weeks` pairs each natural week's use with whether it has ended. A week
    still running counts once it has reached this plan's limit, and its use so
    far always counts against the room left.
    """
    # Rounded so that converting between plan sizes adds no floating-point noise.
    percents = [round(d / times * 100, 3) for d, _ in demand]
    weekly = [(round(w / times * 100, 3), ended) for w, ended in weeks]
    counted = [p for p, ended in weekly if ended or p >= 100]
    return {
        "medianPercent": round(statistics.median(percents)),
        "mostPercent": round(max(percents + [p for p, _ in weekly])),
        "windowsAtLimit": sum(p >= 100 for p in percents),
        # Windows that reached your limit used less than they needed, so a
        # bigger plan may or may not have been enough for them.
        "unknownWindows": sum(bool(hit) and p < 100 for p, (_, hit) in zip(percents, demand)),
        "weeks": len(counted),
        "weeksAtLimit": sum(p >= 100 for p in counted),
    }


def coming_change(current, grandfathered, now):
    """The first change to the plan's size within SOON: (time, size today, new size)."""
    today = times_plus(current, now, grandfathered)
    dates = [epoch(p["from"]) for p in current.get("timesPlus") or [] if p["from"]]
    if grandfathered:
        dates.append(epoch(current["grandfathered"]["previousUntil"]))
    for when in sorted(d for d in dates if now < d <= now + SOON):
        times = times_plus(current, when, grandfathered)
        if times != today:
            return when, today, times
    return None


def compare_plans(plans, sized, plan, recent, weeks, now):
    """The same use on each plan at its size today, and any coming change to yours.

    The coming change is reported even without enough history for the rest.
    """
    by_type, kept, size = sized
    out = {"checked": plans["checked"]}
    out["stale"] = now - epoch(plans["checked"] + "T00:00:00+00:00") > STALE_DAYS * 86400
    current = by_type.get(plan)
    if current is None:
        out["note"] = f'plan type "{plan}" is not in the plans file'
        return out
    out.update(
        current=current["name"],
        nameInferred=bool(current.get("planTypeInferred")),
        grandfathered=plan in kept,
        comparison=[],
        notCompared=[],
        change=None,
    )
    change = coming_change(current, plan in kept, now)
    if change:
        when, today, times = change
        out["change"] = {"date": day(when), "timesPlus": times, "previousTimesPlus": today}
    if len(recent) < MINIMUM:
        return out
    demand = [(plus_weeks(w["steps"], size, w["plan"]), w["limitReachedAt"]) for w in recent]
    used = [(plus_weeks(w["steps"], size, plan), w["ended"]) for w in weeks]
    if any(d is None for d, _ in demand + used):
        out["note"] = "the size of a plan you used is not in the plans file"
        return out
    for other in plans["plans"]:
        yours = other is current
        times = times_plus(other, now, yours and plan in kept)
        if times is None:
            out["notCompared"].append(other["name"])
            continue
        entry = {"name": other["name"], "usdPerMonth": other["usdPerMonth"], "timesPlus": times}
        out["comparison"].append({**entry, "yours": yours, **fit(demand, used, times)})
    if change:
        then = out["change"]
        then.update(fit(demand, used, change[2]))
        then["verdict"] = judge(
            len(recent), then["windowsAtLimit"], then["weeks"], then["weeksAtLimit"]
        )
    return out


def cheapest_that_fits(compared):
    """The cheapest plan below yours that every window and week would have fit in, with room."""
    rows = (compared or {}).get("comparison", [])
    yours = [row["usdPerMonth"] for row in rows if row["yours"]]
    fits = [
        row
        for row in rows
        if yours
        and row["usdPerMonth"] < yours[0]
        and row["mostPercent"] < ROOM
        and not row["unknownWindows"]
    ]
    return min(fits, key=lambda row: row["usdPerMonth"])["name"] if fits else None


def advise_plan(readings, now, count=WINDOWS, plans=None):
    """Facts about the latest closed windows on the current plan, and a verdict.

    With the plans file, the same use is also compared with every plan whose
    size is known, and a cheaper plan that would have stayed below ROOM % in
    every window and week, even without early renewals, turns `enough` into
    `could_go_lower`.
    """
    found, left_out = windows(readings, now)
    sized = None
    if plans:
        # Rebuilt knowing each plan's size, so that a change of size is not use.
        sized = sizing(plans, found)
        found, left_out = windows(readings, now, sized[2])
    plan, stretch = current_stretch(found)
    recent = stretch[-count:]
    replay = without_resets(found, plan, now)
    # A week counts once it has ended or already reached the limit.
    weeks = [w for w in replay if w["ended"] or w["limitReachedAt"] is not None][-count:]
    hits = [w for w in recent if w["limitReachedAt"]]
    short_weeks = [w for w in weeks if w["limitReachedAt"]]
    verdict = judge(len(recent), len(hits), len(weeks), len(short_weeks))
    compared = None
    if plans and plan:
        # The week still running is a floor for that week on any plan.
        running = [w for w in replay[-1:] if not w["ended"] and w["limitReachedAt"] is None]
        compared = compare_plans(plans, sized, plan, recent, weeks + running, now)
    lower = cheapest_that_fits(compared) if verdict == "enough" else None
    if lower:
        verdict = "could_go_lower"
        compared["lowerPlan"] = lower
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
        "plans": compared,
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
# The verdict's opening words, for the plan after a coming change.
SHORT_VERDICTS = {
    "short": "short",
    "enough_thanks_to_early_renewals": "enough only thanks to early renewals",
    "enough": "enough",
}


def outcome(row, windows_count):
    text = (
        f"median {row['medianPercent']} %, limit in {row['windowsAtLimit']} of "
        f"{windows_count} windows ({row['weeksAtLimit']} of {row['weeks']} weeks "
        "without early renewals)"
    )
    if row["unknownWindows"]:
        text += f"; {row['unknownWindows']} more reached your limit, so what they needed is unknown"
    return text


def change_lines(compared, windows_count):
    """A coming change to the user's plan, with what it would mean when known."""
    change = (compared or {}).get("change")
    if not change:
        return []
    why = " (your grandfathered size ends)" if compared["grandfathered"] else ""
    text = (
        f"- Coming change: from {change['date']}, {compared['current']} includes "
        f"{change['timesPlus']}x Plus instead of {change['previousTimesPlus']}x{why}."
    )
    if "verdict" in change:
        text += (
            f" The same use: {outcome(change, windows_count)}. "
            f"Verdict then: {SHORT_VERDICTS[change['verdict']]}."
        )
    return [text]


def plan_lines(compared, windows_count):
    """The comparison with other plans and any coming change, as summary lines."""
    if not compared:
        return []
    out = []
    if compared.get("comparison"):
        stale = "; over 60 days ago, they may have changed" if compared["stale"] else ""
        out.append(
            "- The same use on each plan at its size today (multiples of Plus that OpenAI "
            f"has announced, checked {compared['checked']}{stale}):"
        )
        for row in compared["comparison"]:
            yours = " (yours)" if row["yours"] else ""
            out.append(
                f"  - {row['name']}{yours}, ${row['usdPerMonth']}/month, "
                f"{row['timesPlus']}x Plus: {outcome(row, windows_count)}."
            )
        out += [f"  - {name}: not compared, no confirmed size." for name in compared["notCompared"]]
    if "note" in compared:
        out.append(f"- Not compared with other plans: {compared['note']}.")
    return out + change_lines(compared, windows_count)


def markdown(advice):
    """A short plain summary; the agent explains it in the user's words."""
    plan, recent = advice["plan"], advice["windows"]
    if not recent:
        if advice["historySince"] is None:
            return "Codex: no weekly quota readings in the local logs yet."
        text = (
            f"Codex: no closed weekly window on the current plan yet (readings since "
            f"{advice['historySince']}). A verdict needs {MINIMUM}."
        )
        return "\n".join([text, *change_lines(advice.get("plans"), 0)])
    compared = advice.get("plans") or {}
    name = ""
    if compared.get("current"):
        name = f" ({'probably ' if compared['nameInferred'] else ''}{compared['current']})"
    out = [
        f'Codex weekly allowance, plan "{plan or "unknown"}"{name}: last {len(recent)} closed '
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
    out += plan_lines(advice.get("plans"), len(recent))
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
    elif advice["verdict"] == "could_go_lower":
        rows = {row["name"]: row for row in compared["comparison"]}
        lower, yours = rows[compared["lowerPlan"]], rows[compared["current"]]
        out.append(
            f"Verdict: enough, with room to spare. {lower['name']} would have stayed under "
            f"{ROOM} % every week, even without early renewals, for "
            f"${yours['usdPerMonth'] - lower['usdPerMonth']} less a month. This judges "
            "the weekly allowance only."
        )
    else:
        out.append("Verdict: " + VERDICTS[advice["verdict"]])
    return "\n".join(out)

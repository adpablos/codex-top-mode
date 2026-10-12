import unittest

from plan_fit import WEEK, advise_plan, markdown, times_plus, windows
from usage_monitor import epoch

DAY = 24 * 3600
START = epoch("2033-05-02T00:00:00Z")
NOW = epoch("2033-06-30T00:00:00Z")


# Fictional sizes and dates, shaped like references/plans.json.
PLANS = {
    "checked": "2033-06-20",
    "plans": [
        {
            "name": "Plus",
            "planType": "plus",
            "usdPerMonth": 20,
            "timesPlus": [{"from": None, "value": 1}],
        },
        {
            "name": "Pro 100",
            "planType": "prolite",
            "planTypeInferred": True,
            "usdPerMonth": 100,
            "timesPlus": [{"from": None, "value": 5}],
        },
        {
            "name": "Pro 200",
            "planType": "pro",
            "usdPerMonth": 200,
            "timesPlus": [
                {"from": None, "value": 20},
                {"from": "2033-06-15T00:00:00Z", "value": 10},
            ],
            "grandfathered": {
                "activeFrom": "2033-06-08T00:00:00Z",
                "activeUntil": "2033-06-15T00:00:00Z",
                "previousUntil": "2033-07-15T00:00:00Z",
            },
        },
        {"name": "Pro 500", "planType": None, "usdPerMonth": 500, "timesPlus": []},
    ],
}


def window(start, peak, plan="pro", hours=6 * 24):
    """Hourly readings of a window that starts at `start` and fills evenly to `peak`."""
    return [(start + h * 3600, peak * h / hours, start + WEEK, plan) for h in range(1, hours + 1)]


def weeks(*peaks, plan="pro", every=WEEK, first=START):
    readings = []
    for i, peak in enumerate(peaks):
        readings += window(first + i * every, peak, plan, hours=int(every * 6 / 7 / 3600))
    return readings


class WindowTests(unittest.TestCase):
    def test_windows_follow_their_renewal_time_and_note_early_renewals(self):
        first = window(START, 40, hours=72)
        # Readings of one window give its renewal time to within seconds.
        first[10] = (*first[10][:2], START + WEEK + 2, "pro")
        second = window(START + 3 * DAY, 30)
        found, left_out = windows(first + second, NOW)
        self.assertEqual(left_out, 0)
        self.assertEqual([w["peakPercent"] for w in found], [40, 30])
        self.assertTrue(found[0]["early"])
        self.assertEqual(found[0]["renewedAt"], START + 3 * DAY)
        self.assertFalse(found[1]["early"])
        self.assertTrue(found[1]["closed"])

    def test_a_window_that_has_not_renewed_is_open(self):
        found, _ = windows(window(NOW - DAY, 10), NOW)
        self.assertFalse(found[0]["closed"])

    def test_a_plan_change_is_not_use(self):
        before = window(START, 60, plan="prolite", hours=24)
        # The new plan's percentage already includes what was used before.
        after = [(START + 25 * 3600, 15.0, START + WEEK, "pro")]
        after.append((START + 26 * 3600, 20.0, START + WEEK, None))
        [found], _ = windows(before + after, NOW)
        self.assertEqual((found["plan"], found["peakPercent"]), ("pro", 20))
        self.assertTrue(found["planChanged"])
        self.assertEqual([s[1:] for s in found["steps"] if s[2] == "pro"], [(5.0, "pro")])

    def test_a_parallel_meter_is_left_out(self):
        real = window(START, 50, hours=72)
        # A second meter that stays at 0 % while the account's window fills.
        meter = [
            (START + 10 * 3600 + m * 600, 0.0, START + 10 * 3600 + WEEK, "pro") for m in range(60)
        ]
        found, left_out = windows(real + meter, NOW)
        self.assertEqual([w["peakPercent"] for w in found], [50])
        self.assertEqual(left_out, 60)

    def test_of_two_identical_parallel_meters_one_is_kept(self):
        one = [(START + m * 600, 0.0, START + WEEK, "pro") for m in range(60)]
        other = [(stamp + 60, used, START + WEEK + 3600, plan) for stamp, used, _, plan in one]
        found, left_out = windows(one + other, NOW)
        self.assertEqual((len(found), left_out), (1, 60))

    def test_a_window_left_out_does_not_hide_another(self):
        def meter(start_hour, peak, renews):
            steps = range(19)  # every 10 minutes for 3 hours
            return [(START + start_hour * 3600 + s * 600, peak, renews, "pro") for s in steps]

        # The middle meter runs alongside both others, which never overlap each other.
        first = meter(0, 10.0, START + WEEK)
        middle = meter(1.5, 20.0, START + WEEK + 3600)
        last = meter(3.5, 30.0, START + WEEK + 7200)
        found, left_out = windows(first + middle + last, NOW)
        self.assertEqual(([w["peakPercent"] for w in found], left_out), ([10, 30], len(middle)))

    def test_a_late_reading_of_an_old_window_does_not_hide_the_new_one(self):
        old = window(START, 100, hours=48)
        new = window(START + 2 * DAY + 3600, 20)
        late = [(START + 2 * DAY + 3 * 3600, 100.0, START + WEEK, "pro")]
        found, left_out = windows(old + new + late, NOW)
        self.assertEqual(([w["peakPercent"] for w in found], left_out), ([100, 20], 0))
        self.assertTrue(found[0]["early"])


class VerdictTests(unittest.TestCase):
    def test_enough(self):
        advice = advise_plan(weeks(*[40] * 8), NOW)
        self.assertEqual(advice["verdict"], "enough")
        self.assertEqual(advice["medianPeakPercent"], 40)
        self.assertEqual(len(advice["windows"]), 8)
        self.assertEqual([w["usedPercent"] for w in advice["withoutEarlyRenewals"]], [40] * 8)
        self.assertTrue(advice["includesTopModeRuns"])

    def test_short_when_the_limit_is_reached_in_more_than_1_of_4(self):
        advice = advise_plan(weeks(100, 40, 100, 40, 100, 40, 40, 40), NOW)
        self.assertEqual(advice["verdict"], "short")
        self.assertEqual([w["limitReached"] is not None for w in advice["windows"]].count(True), 3)
        # Use stopped at the limit, so those weeks needed at least what they used.
        self.assertEqual([w["atLeast"] for w in advice["withoutEarlyRenewals"]].count(True), 3)
        twice = advise_plan(weeks(100, 40, 100, 40, 40, 40, 40, 40), NOW)
        self.assertEqual(twice["verdict"], "enough")

    def test_enough_only_thanks_to_early_renewals(self):
        # Renewed every 3.5 days at 70 %: a natural week would have needed 140 %.
        advice = advise_plan(weeks(*[70] * 12, every=WEEK // 2), NOW)
        self.assertEqual(advice["verdict"], "enough_thanks_to_early_renewals")
        # The last one ran its full week: no later window renewed it.
        self.assertEqual([w["renewedEarly"] for w in advice["windows"]], [True] * 7 + [False])
        replay = advice["withoutEarlyRenewals"]
        self.assertEqual({(w["usedPercent"], w["reachedLimit"]) for w in replay}, {(140, True)})

    def test_a_natural_week_counts_once_it_runs_out_even_before_it_ends(self):
        # Four windows at 30 %, each renewed the next day: 120 % within one week.
        advice = advise_plan(weeks(*[30] * 5, every=DAY), START + 6 * DAY)
        self.assertEqual(len(advice["windows"]), 4)
        self.assertEqual(advice["withoutEarlyRenewals"][0]["reachedLimit"], True)
        self.assertEqual(advice["verdict"], "enough_thanks_to_early_renewals")

    def test_a_verdict_needs_four_closed_windows_on_the_current_plan(self):
        readings = weeks(90, 90, 90, 90, plan="prolite")
        readings += weeks(20, 20, 20, plan="pro", first=START + 4 * WEEK)
        advice = advise_plan(readings, NOW)
        self.assertEqual((advice["plan"], advice["verdict"]), ("pro", "not_enough_history"))
        self.assertEqual(len(advice["windows"]), 3)
        # The window still running does not count.
        readings += weeks(20, 20, plan="pro", first=START + 7 * WEEK)
        advice = advise_plan(readings, NOW)
        self.assertEqual((len(advice["windows"]), advice["verdict"]), (4, "enough"))
        self.assertEqual(advice["historySince"], "2033-05-02")

    def test_markdown_states_facts_sources_and_verdict(self):
        text = markdown(advise_plan(weeks(100, 40, 100, 40, 40, 40, 40, 40), NOW))
        self.assertIn('plan "pro": last 8 closed windows (2033-05-02 to 2033-06-27)', text)
        self.assertIn("100, 40, 100, 40, 40, 40, 40, 40 % (median 40 %)", text)
        self.assertIn("Reached the limit in 2 of 8, the last on 2033-05-22.", text)
        self.assertIn("would have reached the limit in 2 of 8 weeks (most: at least 100 %", text)
        self.assertIn("cannot be told apart", text)
        self.assertIn("Verdict: enough.", text)
        meter = [
            (START + 10 * 3600 + m * 600, 0.0, START + 10 * 3600 + WEEK, "pro") for m in range(60)
        ]
        advice = advise_plan(weeks(*[40] * 8) + meter, NOW)
        self.assertIn("Left out 60 readings", markdown({**advice, "compressedLogs": 2}))
        self.assertIn("2 compressed logs", markdown({**advice, "compressedLogs": 2}))

    def test_markdown_without_enough_history(self):
        self.assertIn("no weekly quota readings", markdown(advise_plan([], NOW)))
        text = markdown(advise_plan(window(NOW - DAY, 10), NOW))
        self.assertIn("no closed weekly window", text)
        text = markdown(advise_plan(weeks(40, 40), NOW))
        self.assertIn("Not enough history for a verdict: 2 closed windows", text)


class PlanTests(unittest.TestCase):
    def rows(self, advice):
        return {row["name"]: row for row in advice["plans"]["comparison"]}

    def test_a_plan_size_follows_its_changes_and_grandfathering(self):
        pro = PLANS["plans"][2]
        before, after = epoch("2033-06-14T00:00:00Z"), epoch("2033-06-20T00:00:00Z")
        self.assertEqual((times_plus(pro, before), times_plus(pro, after)), (20, 10))
        self.assertEqual(times_plus(pro, after, grandfathered=True), 20)
        self.assertEqual(times_plus(pro, epoch("2033-07-15T00:00:00Z"), grandfathered=True), 10)
        self.assertIsNone(times_plus(PLANS["plans"][3], after))

    def test_the_same_use_on_each_plan_and_the_coming_change(self):
        # Active during the eligibility week: keeps 20x Plus until 2033-07-15.
        advice = advise_plan(weeks(*[70] * 8), NOW, plans=PLANS)
        compared = advice["plans"]
        self.assertEqual((compared["current"], compared["grandfathered"]), ("Pro 200", True))
        rows = self.rows(advice)
        self.assertEqual(rows["Plus"]["medianPercent"], 1400)
        self.assertEqual(rows["Pro 100"]["windowsAtLimit"], 8)
        self.assertEqual((rows["Pro 200"]["timesPlus"], rows["Pro 200"]["medianPercent"]), (20, 70))
        self.assertEqual(compared["notCompared"], ["Pro 500"])
        self.assertEqual(advice["verdict"], "enough")
        change = compared["change"]
        self.assertEqual((change["date"], change["timesPlus"]), ("2033-07-15", 10))
        self.assertEqual((change["medianPercent"], change["verdict"]), (140, "short"))
        text = markdown(advice)
        self.assertIn('plan "pro" (Pro 200): last 8', text)
        self.assertIn("checked 2033-06-20):", text)
        self.assertIn(
            "  - Plus, $20/month, 1x Plus: median 1400 %, limit in 8 of 8 windows (8 of", text
        )
        self.assertIn("  - Pro 500: not compared, no confirmed size.", text)
        self.assertIn(
            "from 2033-07-15, Pro 200 includes 10x Plus instead of 20x (your grandfathered "
            "size ends). The same use: median 140 %",
            text,
        )
        self.assertIn("Verdict then: short.", text)

    def test_on_your_own_plan_the_comparison_matches_the_windows(self):
        # Seven uneven steps to 100 %: converting them must not land just under the limit.
        readings = []
        for i, peak in enumerate((100, 40, 100, 40, 40, 40, 40, 40)):
            readings += window(START + i * WEEK, peak, hours=7)
        advice = advise_plan(readings, NOW, plans=PLANS)
        yours = self.rows(advice)["Pro 200"]
        self.assertEqual((yours["windowsAtLimit"], yours["unknownWindows"]), (2, 0))
        reached = [w["reachedLimit"] for w in advice["withoutEarlyRenewals"]]
        self.assertEqual(yours["weeksAtLimit"], reached.count(True))

    def test_a_change_of_size_on_the_same_plan_is_not_use(self):
        resized = {"from": "2033-06-24T00:00:00Z", "value": 5}
        pro100 = {**PLANS["plans"][1], "timesPlus": [{"from": None, "value": 10}, resized]}
        plans = {**PLANS, "plans": [PLANS["plans"][0], pro100, *PLANS["plans"][2:]]}
        readings = weeks(*[40] * 7, plan="prolite")
        start, renews = START + 7 * WEEK, START + 8 * WEEK
        # 40 % of 10x Plus shows as 80 % of 5x Plus once the plan shrinks; then 5 % more.
        readings += [
            (start + 3 * DAY, 40.0, renews, "prolite"),
            (start + 4 * DAY + 3600, 80.0, renews, "prolite"),
            (start + 5 * DAY, 85.0, renews, "prolite"),
        ]
        advice = advise_plan(readings, NOW, plans=plans)
        self.assertEqual(advice["windows"][-1]["peakPercent"], 85)
        yours = self.rows(advice)["Pro 100"]
        self.assertEqual((yours["timesPlus"], yours["mostPercent"]), (5, 85))
        self.assertEqual(yours["windowsAtLimit"], 0)

    def test_a_natural_week_adds_up_use_across_a_change_of_size(self):
        resized = {"from": "2033-06-22T22:00:00Z", "value": 5}
        pro100 = {**PLANS["plans"][1], "timesPlus": [{"from": None, "value": 10}, resized]}
        plans = {**PLANS, "plans": [PLANS["plans"][0], pro100, *PLANS["plans"][2:]]}
        readings = weeks(*[10] * 6, plan="prolite")
        # Five windows renewed daily, 15 % each: 4.5x Plus at 10x, then 1.5x Plus at 5x.
        for d in range(5):
            readings += window(START + 7 * WEEK + d * DAY, 15, plan="prolite", hours=20)
        advice = advise_plan(readings, NOW, plans=plans)
        week = advice["withoutEarlyRenewals"][-1]
        self.assertEqual((week["usedPercent"], week["reachedLimit"]), (120, True))
        self.assertEqual(self.rows(advice)["Pro 100"]["weeksAtLimit"], 1)

    def test_a_smaller_size_after_the_last_use_still_fills_the_week(self):
        resized = {"from": "2033-06-24T00:00:00Z", "value": 5}
        pro100 = {**PLANS["plans"][1], "timesPlus": [{"from": None, "value": 10}, resized]}
        plans = {**PLANS, "plans": [PLANS["plans"][0], pro100, *PLANS["plans"][2:]]}
        readings = weeks(*[10] * 6, plan="prolite")
        # Four windows renewed daily, 15 % each at 10x: 6x Plus, more than 5x once it shrinks.
        for d in range(4):
            readings += window(START + 7 * WEEK + d * DAY, 15, plan="prolite", hours=20)
        renews = START + 7 * WEEK + 3 * DAY + WEEK
        readings.append((epoch("2033-06-24T01:00:00Z"), 30.0, renews, "prolite"))
        advice = advise_plan(readings, NOW, plans=plans)
        week = advice["withoutEarlyRenewals"][-1]
        self.assertEqual((week["usedPercent"], week["reachedLimit"]), (120, True))

    def test_the_week_still_running_counts_against_the_room_left(self):
        readings = weeks(*[3] * 8)
        # Then a window renewed every day: 2 % each, 6 % of Pro 200 in one running week.
        for d in range(3):
            readings += window(START + 8 * WEEK + d * DAY, 2, hours=20)
        advice = advise_plan(readings, NOW, plans=PLANS)
        self.assertEqual(self.rows(advice)["Plus"]["mostPercent"], 120)
        self.assertEqual(
            (advice["verdict"], advice["plans"]["lowerPlan"]), ("could_go_lower", "Pro 100")
        )

    def test_a_coming_change_is_shown_even_with_little_history(self):
        advice = advise_plan(weeks(40, 40, first=START + 5 * WEEK), NOW, plans=PLANS)
        self.assertEqual(advice["verdict"], "not_enough_history")
        self.assertEqual(advice["plans"]["change"]["date"], "2033-07-15")
        line = (
            "- Coming change: from 2033-07-15, Pro 200 includes 10x Plus instead of 20x "
            "(your grandfathered size ends)."
        )
        self.assertIn(line, markdown(advice))
        opened = window(epoch("2033-06-10T00:00:00Z"), 10, hours=24)
        text = markdown(advise_plan(opened, epoch("2033-06-16T00:00:00Z"), plans=PLANS))
        self.assertIn("no closed weekly window", text)
        self.assertIn(line, text)

    def test_grandfathering_ignores_another_accounts_meter(self):
        readings = weeks(*[40] * 4)
        readings += window(epoch("2033-06-05T00:00:00Z"), 40, hours=71)
        readings += weeks(40, 40, first=epoch("2033-06-15T00:00:00Z"))
        # Another account's meter, on Pro during the eligibility week, beside this one.
        begins = epoch("2033-06-06T00:00:00Z")
        meter = [(begins + m * 600, 0.0, begins + WEEK, "pro") for m in range(3 * 24 * 6)]
        advice = advise_plan(readings + meter, NOW, plans=PLANS)
        self.assertEqual(advice["parallelReadingsLeftOut"], len(meter))
        self.assertFalse(advice["plans"]["grandfathered"])
        self.assertEqual(self.rows(advice)["Pro 200"]["timesPlus"], 10)

    def test_a_cheaper_plan_that_would_have_been_enough(self):
        advice = advise_plan(weeks(*[3] * 8), NOW, plans=PLANS)
        self.assertEqual(
            (advice["verdict"], advice["plans"]["lowerPlan"]), ("could_go_lower", "Plus")
        )
        self.assertIn(
            "Verdict: enough, with room to spare. Plus would have stayed under 80 % every week, "
            "even without early renewals, for $180 less a month.",
            markdown(advice),
        )
        # At 80 % of Plus there is no room left: the next plan up is the cheaper one.
        tight = advise_plan(weeks(*[4] * 8), NOW, plans=PLANS)
        self.assertEqual(self.rows(tight)["Plus"]["mostPercent"], 80)
        self.assertEqual(tight["plans"]["lowerPlan"], "Pro 100")

    def test_a_bigger_plan_cannot_tell_how_much_a_window_at_the_limit_needed(self):
        readings = weeks(100, 40, 100, 40, 100, 40, 40, 40, plan="prolite")
        advice = advise_plan(readings, NOW, plans={**PLANS, "checked": "2033-04-01"})
        self.assertEqual(advice["verdict"], "short")
        rows = self.rows(advice)
        # 5x Plus used fully is half of Pro 200's 10x, but those weeks stopped at the limit.
        self.assertEqual(
            (rows["Pro 200"]["windowsAtLimit"], rows["Pro 200"]["unknownWindows"]), (0, 3)
        )
        self.assertIsNone(advice["plans"]["change"])
        text = markdown(advice)
        self.assertIn('plan "prolite" (probably Pro 100)', text)
        self.assertIn("; 3 more reached your limit, so what they needed is unknown.", text)
        self.assertIn("over 60 days ago, they may have changed", text)

    def test_plans_that_cannot_be_compared(self):
        advice = advise_plan(weeks(*[40] * 8, plan="team"), NOW, plans=PLANS)
        self.assertEqual(advice["plans"]["note"], 'plan type "team" is not in the plans file')
        self.assertIn("- Not compared with other plans: plan type", markdown(advice))
        before = window(START, 60, plan="free", hours=24)
        after = [(START + 25 * 3600, 15.0, START + WEEK, "pro")]
        readings = before + after + weeks(*[40] * 4, first=START + WEEK)
        advice = advise_plan(readings, NOW, plans=PLANS)
        self.assertEqual(
            advice["plans"]["note"], "the size of a plan you used is not in the plans file"
        )
        # Too little history to compare plans, but the plan is still named.
        short = advise_plan(weeks(40, 40), NOW, plans=PLANS)["plans"]
        self.assertEqual(
            (short["current"], short["comparison"], short["change"]), ("Pro 200", [], None)
        )


if __name__ == "__main__":
    unittest.main()

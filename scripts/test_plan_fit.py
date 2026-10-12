import unittest

from plan_fit import WEEK, advise_plan, markdown, windows
from usage_monitor import epoch

DAY = 24 * 3600
START = epoch("2033-05-02T00:00:00Z")
NOW = epoch("2033-06-30T00:00:00Z")


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


if __name__ == "__main__":
    unittest.main()

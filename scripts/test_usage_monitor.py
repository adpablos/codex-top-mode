import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from usage_monitor import (
    epoch,
    expiry_advice,
    observe,
    replenished,
    snapshot,
    stop_new_work_at,
    weekly,
)

START = 2000000000


def reading(used=17, resets=3, now=START, reset_at=START + 86400, grants=None):
    payload = {
        "accountId": "synthetic-private-identity",
        "rateLimitsByLimitId": {
            "codex": {
                "primary": {
                    "usedPercent": used,
                    "windowDurationMins": 10080,
                    "resetsAt": reset_at,
                },
                "credits": {"balance": "secret"},
            }
        },
        "rateLimitResetCredits": {
            "availableCount": resets,
            "credits": [
                {"id": "synthetic-credit-id", "status": "available", "grantedAt": t}
                for t in (grants or [])
            ],
        },
    }
    return snapshot(payload, now)


def policy():
    return {
        "mode": "top",
        "effectiveStopAt": START + 4 * 3600,
        "last": reading(),
    }


def run_window(current, stop_on_renewal=True):
    """An eight-hour run started the way the manual-run contract describes."""
    renewal = weekly(current)["resetsAt"] if weekly(current) else None
    return {
        "mode": "top",
        "startedAt": current["observedAt"],
        "effectiveStopAt": current["observedAt"] + 8 * 3600,
        "baseline": current,
        "last": current,
        "stopOnScheduledWeeklyRenewal": stop_on_renewal,
        "scheduledWeeklyStopAt": renewal,
        "detectLowUsageRenewalShift": True,
    }


class MonitorTests(unittest.TestCase):
    def test_no_identifiers_or_balance_are_persisted(self):
        text = json.dumps(reading(grants=[START - 100]))
        for forbidden in (
            "synthetic-private-identity",
            "synthetic-credit-id",
            "secret",
            "accountId",
        ):
            self.assertNotIn(forbidden, text)

    def test_confirm_weekly_restoration_with_two_fresh_reads(self):
        state, event = observe(policy(), reading(0, now=START + 30))
        self.assertEqual(event, "confirm_replenishment_with_fresh_read")
        self.assertEqual(state["mode"], "top")
        state, event = observe(state, reading(1, now=START + 51))
        self.assertEqual(event, "quota_replenishment_confirmed")
        self.assertEqual(state["mode"], "normal")

    def test_transient_reduction_does_not_stop_work(self):
        state, _ = observe(policy(), reading(0, now=START + 30))
        state, _ = observe(state, reading(18, now=START + 60))
        self.assertEqual(state["mode"], "top")
        self.assertIsNone(state["pendingReplenishment"])

    def test_same_observation_cannot_confirm_reset(self):
        state, _ = observe(policy(), reading(0, now=START + 30))
        state, event = observe(state, reading(0, now=START + 30))
        self.assertEqual(event, "stale_observation")
        self.assertEqual(state["mode"], "top")

    def test_natural_weekly_reset_is_separate(self):
        state = policy()
        state["last"] = reading(reset_at=START + 30)
        state, event = observe(state, reading(0, now=START + 31))
        self.assertEqual(event, "scheduled_weekly_reset")
        self.assertEqual(state["mode"], "top")

    def test_short_window_replenishment_is_not_global_evidence(self):
        state = policy()
        state["last"]["windows"][0]["durationMinutes"] = 300
        current = reading(0, now=START + 30)
        current["windows"][0]["durationMinutes"] = 300
        state, event = observe(state, current)
        self.assertEqual(event, "unchanged")
        self.assertEqual(state["mode"], "top")

    def test_banked_count_is_authoritative_even_without_detail_rows(self):
        state, event = observe(policy(), reading(resets=4, now=START + 30))
        self.assertEqual(event, "banked_reset_added")
        self.assertEqual(state["effectiveStopAt"], START + 4 * 3600)

    def test_new_grant_can_coincide_with_expiration_and_no_net_count_change(self):
        state, event = observe(policy(), reading(resets=3, now=START + 30, grants=[START + 10]))
        self.assertEqual(event, "banked_reset_added")
        self.assertEqual(state["mode"], "top")

    def test_old_detail_row_appearing_later_is_not_a_new_reset(self):
        _, event = observe(policy(), reading(now=START + 30, grants=[START - 100]))
        self.assertEqual(event, "unchanged")

    def test_missing_or_invalid_usage_is_not_zero(self):
        for payload in (
            {},
            {"isError": True},
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": float("nan"),
                            "windowDurationMins": 10080,
                        }
                    }
                }
            },
        ):
            current = snapshot(payload, START + 30)
            state, event = observe(policy(), current)
            self.assertEqual(event, "usage_unavailable")
            self.assertEqual(state["mode"], "top")

    def test_time_limit_still_holds_if_usage_is_unavailable(self):
        state, event = observe(policy(), snapshot({}, START + 4 * 3600))
        self.assertEqual(event, "time_window_ended")
        self.assertEqual(state["mode"], "normal")

    def test_missing_poll_does_not_erase_previous_weekly_evidence(self):
        state, _ = observe(policy(), reading(now=START + 10))
        state, _ = observe(state, snapshot({}, START + 20))
        state, event = observe(state, reading(0, now=START + 30))
        self.assertEqual(event, "confirm_replenishment_with_fresh_read")

    def test_missing_credit_count_does_not_erase_previous_count(self):
        state, _ = observe(policy(), reading(now=START + 10))
        state, _ = observe(state, snapshot({}, START + 20))
        state, event = observe(state, reading(resets=4, now=START + 30))
        self.assertEqual(event, "banked_reset_added")

    def test_restoration_wins_when_a_saved_credit_also_arrives(self):
        state, _ = observe(policy(), reading(0, resets=4, now=START + 30))
        state, event = observe(state, reading(1, resets=4, now=START + 51))
        self.assertEqual(event, "quota_replenishment_confirmed")
        self.assertEqual(state["mode"], "normal")

    def test_saved_resets_never_extend_the_deadline(self):
        state = policy()
        state["bankedStopAt"] = START + 6 * 3600  # left by older versions; ignored
        state, event = observe(state, reading(resets=4, now=START + 30))
        self.assertEqual(event, "banked_reset_added")
        self.assertEqual(state["effectiveStopAt"], START + 4 * 3600)
        state, event = observe(state, reading(resets=5, now=START + 4 * 3600))
        self.assertEqual(event, "time_window_ended")
        self.assertEqual(state["mode"], "normal")

    def test_late_credit_does_not_revive_expired_work_window(self):
        state, event = observe(policy(), reading(resets=4, now=START + 4 * 3600))
        self.assertEqual(event, "time_window_ended")
        self.assertEqual(state["mode"], "normal")
        self.assertEqual(state["effectiveStopAt"], START + 4 * 3600)

    def test_confirmation_after_scheduled_renewal_is_not_early_reset(self):
        state = policy()
        state["last"] = reading(reset_at=START + 100)
        state, event = observe(state, reading(0, now=START + 30))
        self.assertEqual(event, "confirm_replenishment_with_fresh_read")
        state, event = observe(state, reading(0, now=START + 101))
        self.assertEqual(event, "scheduled_weekly_reset")
        self.assertEqual(state["mode"], "top")
        self.assertIsNone(state["pendingReplenishment"])

    def test_naive_timestamp_cannot_depend_on_machine_timezone(self):
        self.assertIsNone(epoch("2033-05-18T03:33:20"))
        with self.assertRaises(ValueError):
            observe(policy(), reading(now="2033-05-18T03:33:20"))

    def test_explicit_per_limit_map_does_not_mix_with_legacy_bucket(self):
        legacy = {"primary": {"usedPercent": 0, "windowDurationMins": 10080}}
        for buckets in ({}, {"other": legacy}):
            current = snapshot({"rateLimitsByLimitId": buckets, "rateLimits": legacy}, START + 30)
            state, event = observe(policy(), current)
            self.assertEqual(event, "usage_unavailable")
            self.assertEqual(state["mode"], "top")
        self.assertEqual(len(snapshot({"rateLimits": legacy}, START)["windows"]), 1)

    def test_invalid_stop_time_is_rejected_without_mutating_state(self):
        state = policy()
        state["effectiveStopAt"] = "2033-05-18T03:33:20"
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            observe(state, reading(now=START + 30))
        self.assertEqual(state, before)

    def test_cli_preserves_envelope_and_writes_only_sanitized_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"usageMonitor": policy(), "scope": "synthetic-work"}))
            payload = {"accountId": "synthetic-private-id", "token": "synthetic-secret"}
            run = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("usage_monitor.py")),
                    "--state",
                    str(path),
                    "--observed-at",
                    str(START + 30),
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            # CLI time is an ISO timestamp; an unqualified numeric string must be rejected.
            self.assertNotEqual(run.returncode, 0)
            before = path.read_text()
            run = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("usage_monitor.py")),
                    "--state",
                    str(path),
                    "--observed-at",
                    "2033-05-18T03:33:50Z",
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=True,
            )
            saved = json.loads(path.read_text())
            self.assertEqual(saved["scope"], "synthetic-work")
            self.assertEqual(json.loads(run.stdout)["event"], "usage_unavailable")
            self.assertNotEqual(path.read_text(), before)
            self.assertNotIn("synthetic-private-id", path.read_text() + run.stdout)
            self.assertNotIn("synthetic-secret", path.read_text() + run.stdout)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_first_poll_keeps_initial_baseline_for_late_grant_details(self):
        state, _ = observe(policy(), reading(now=START + 10))
        state, event = observe(state, reading(now=START + 30, grants=[START + 5]))
        self.assertEqual(event, "banked_reset_added")
        self.assertEqual(state["baseline"]["observedAt"], START)

    def test_zero_authoritative_count_cannot_extend_from_stale_credit_detail(self):
        state, event = observe(policy(), reading(resets=0, now=START + 30, grants=[START + 5]))
        self.assertEqual(event, "unchanged")
        self.assertEqual(state["effectiveStopAt"], START + 4 * 3600)

    def test_late_confirmation_restarts_fresh_pair_against_original_anchor(self):
        state, _ = observe(policy(), reading(0, now=START + 30))
        state, event = observe(state, reading(1, now=START + 1831))
        self.assertEqual(event, "confirm_replenishment_with_fresh_read")
        self.assertEqual(state["mode"], "top")
        state, event = observe(state, reading(1, now=START + 1852))
        self.assertEqual(event, "quota_replenishment_confirmed")
        self.assertEqual(state["mode"], "normal")

    def test_documented_minimum_native_payload_retains_available_expiration(self):
        payload = {
            "rateLimitResetCredits": {
                "availableCount": 1,
                "credits": [
                    {
                        "status": "available",
                        "grantedAt": START - 100,
                        "expiresAt": START + 100,
                    },
                    {
                        "status": "consumed",
                        "grantedAt": START - 200,
                        "expiresAt": START + 200,
                    },
                ],
            }
        }
        current = snapshot(payload, START)
        self.assertEqual(current["grantTimes"], [START - 100])
        self.assertEqual(expiry_advice(current)["dueExpirations"], [START + 100])
        self.assertEqual(expiry_advice(current)["expiryCoverage"], "complete")

    def test_cli_stop_signal_stays_at_confirmation_time_in_normal_mode(self):
        candidate, _ = observe(policy(), reading(0, now=START + 30))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps({"usageMonitor": candidate, "stopNewWorkAt": START + 4 * 3600})
            )
            payload = {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": 0,
                            "windowDurationMins": 10080,
                            "resetsAt": START + 86400,
                        }
                    }
                }
            }
            for observed_at in ("2033-05-18T03:34:11Z", "2033-05-18T03:34:41Z"):
                subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(Path(__file__).with_name("usage_monitor.py")),
                        "--state",
                        str(path),
                        "--observed-at",
                        observed_at,
                    ],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                saved = json.loads(path.read_text())
                self.assertEqual(saved["usageMonitor"]["mode"], "normal")
                self.assertEqual(saved["stopNewWorkAt"], "2033-05-18T03:34:11Z")
                self.assertEqual(saved["usageMonitor"]["effectiveStopAt"], START + 4 * 3600)

    def test_cli_reports_the_earlier_scheduled_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            monitor = policy()
            monitor.update(stopOnScheduledWeeklyRenewal=True, scheduledWeeklyStopAt=START + 3600)
            path.write_text(json.dumps({"usageMonitor": monitor}))
            payload = {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": 18,
                            "windowDurationMins": 10080,
                            "resetsAt": START + 3600,
                        }
                    }
                }
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("usage_monitor.py")),
                    "--state",
                    str(path),
                    "--observed-at",
                    datetime.fromtimestamp(START + 120, timezone.utc).isoformat(),
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["stopNewWorkAt"], START + 3600)
            self.assertEqual(saved["usageMonitor"]["effectiveStopAt"], START + 4 * 3600)

    def test_original_state_is_not_mutated(self):
        original = policy()
        before = copy.deepcopy(original)
        observe(original, reading(0, now=START + 30))
        self.assertEqual(original, before)

    def test_expiry_warning_uses_actual_seven_day_boundary(self):
        observation = reading()
        observation["resetExpirations"] = [
            {"grantedAt": START - 100, "expiresAt": START + 7 * 86400},
            {"grantedAt": START - 200, "expiresAt": START + 8 * 86400},
            {"grantedAt": START - 300, "expiresAt": START - 1},
        ]
        advice = expiry_advice(observation)
        self.assertEqual(advice["dueExpirations"], [START + 7 * 86400])
        self.assertEqual(advice["nextWarningAt"], START + 86400)
        self.assertEqual(advice["expiryCoverage"], "partial")

    def test_missing_expirations_are_unknown_not_thirty_days(self):
        advice = expiry_advice(reading())
        self.assertEqual(advice["dueExpirations"], [])
        self.assertIsNone(advice["nextWarningAt"])
        self.assertEqual(advice["expiryCoverage"], "partial")

    def test_expired_or_consumed_rows_are_not_available_warnings(self):
        observation = snapshot(
            {
                "rateLimitResetCredits": {
                    "availableCount": 0,
                    "credits": [
                        {"status": "consumed", "expiresAt": START + 10},
                        {"status": "available", "expiresAt": START + 20},
                    ],
                }
            },
            START,
        )
        advice = expiry_advice(observation)
        self.assertEqual(advice["dueExpirations"], [])
        self.assertEqual(advice["expiryCoverage"], "complete")

    def test_null_count_does_not_claim_complete_expiry_inventory(self):
        advice = expiry_advice(snapshot({}, START))
        self.assertEqual(advice["expiryCoverage"], "unknown")

    def test_duplicate_expiration_details_do_not_prove_complete_coverage(self):
        observation = reading(resets=2)
        row = {"grantedAt": START - 1, "expiresAt": START + 100}
        observation["resetExpirations"] = [row, row]
        advice = expiry_advice(observation)
        self.assertEqual(advice["expiryCoverage"], "partial")
        self.assertEqual(advice["dueExpirations"], [START + 100])


class BoundaryTests(unittest.TestCase):
    """Exact limits: the moment a stop is due and the size of a real drop."""

    def test_scheduled_renewal_stops_exactly_at_its_time(self):
        monitor = policy()
        monitor.update(stopOnScheduledWeeklyRenewal=True, scheduledWeeklyStopAt=START + 100)
        state, event = observe(monitor, reading(now=START + 99))
        self.assertEqual(state["mode"], "top")
        _, event = observe(monitor, reading(now=START + 100))
        self.assertEqual(event, "scheduled_weekly_renewal_due")
        # A renewal at the deadline itself is still reported as the renewal.
        monitor["scheduledWeeklyStopAt"] = monitor["effectiveStopAt"]
        _, event = observe(monitor, reading(now=START + 4 * 3600))
        self.assertEqual(event, "scheduled_weekly_renewal_due")

    def test_confirmation_needs_a_second_read_20_seconds_to_30_minutes_later(self):
        candidate, _ = observe(policy(), reading(0, now=START + 30))
        for age, confirmed in ((19, False), (20, True), (1800, True), (1801, False)):
            with self.subTest(age=age):
                state, _ = observe(candidate, reading(1, now=START + 30 + age))
                self.assertEqual(state["mode"] == "normal", confirmed)

    def test_a_real_drop_is_at_least_five_points_down_to_two_percent(self):
        def drop(before, after):
            return replenished({"usedPercent": before}, {"usedPercent": after})

        self.assertTrue(drop(6, 1))
        self.assertFalse(drop(5.9, 1))
        self.assertTrue(drop(7, 2))
        self.assertFalse(drop(7, 2.1))

    def test_snapshot_keeps_0_and_100_and_drops_impossible_values(self):
        def windows(used):
            limits = {"primary": {"usedPercent": used, "windowDurationMins": 10080}}
            return snapshot({"rateLimits": limits}, START)["windows"]

        self.assertTrue(windows(0) and windows(100))
        self.assertFalse(windows(-1) or windows(101))
        for count, kept in ((2, 2), (-1, None), (1.5, None)):
            payload = {"rateLimitResetCredits": {"availableCount": count}}
            self.assertEqual(snapshot(payload, START)["availableResets"], kept)


class RunWindowTests(unittest.TestCase):
    def test_the_earlier_of_deadline_and_scheduled_renewal_stops_the_run(self):
        monitor = run_window(reading(now=START + 30, reset_at=START + 90))
        self.assertEqual(stop_new_work_at(monitor), START + 90)
        # The renewal stop holds even when later telemetry is missing.
        monitor, event = observe(monitor, snapshot({}, START + 100))
        self.assertEqual(event, "scheduled_weekly_renewal_due")
        self.assertEqual(stop_new_work_at(monitor), START + 90)
        monitor = run_window(reading(now=START + 30))
        self.assertEqual(stop_new_work_at(monitor), START + 30 + 8 * 3600)
        monitor, event = observe(monitor, reading(now=START + 86401))
        self.assertEqual(event, "time_window_ended")
        self.assertEqual(stop_new_work_at(monitor), START + 30 + 8 * 3600)

    def test_unknown_renewal_still_requires_two_fresh_strong_drop_readings(self):
        monitor = run_window(reading(60, now=START + 30, reset_at=None), stop_on_renewal=False)
        monitor, event = observe(monitor, reading(0, now=START + 60, reset_at=None))
        self.assertEqual(event, "confirm_replenishment_with_fresh_read")
        monitor, event = observe(monitor, reading(0, now=START + 60, reset_at=None))
        self.assertEqual(event, "stale_observation")
        monitor, event = observe(monitor, reading(1, now=START + 81, reset_at=None))
        self.assertEqual(event, "quota_replenishment_confirmed")
        self.assertEqual(monitor["stopReason"], "weekly_quota_replenished")
        self.assertEqual(stop_new_work_at(monitor), START + 81)

    def test_low_usage_shift_requires_two_fresh_reads_before_stopping(self):
        monitor = run_window(reading(1, now=START + 30))
        shifted = START + 2 * 86400
        monitor, event = observe(monitor, reading(0, now=START + 60, reset_at=shifted))
        self.assertEqual(event, "confirm_replenishment_with_fresh_read")
        self.assertEqual(monitor["mode"], "top")
        monitor, _ = observe(monitor, reading(0, now=START + 70, reset_at=shifted))
        self.assertEqual(monitor["mode"], "top")
        monitor, event = observe(monitor, reading(0, now=START + 81, reset_at=shifted))
        self.assertEqual(event, "quota_replenishment_confirmed")
        self.assertEqual(stop_new_work_at(monitor), START + 81)

    def assert_still_running(self, monitor, readings):
        for current in readings:
            monitor, _ = observe(monitor, current)
            self.assertEqual(monitor["mode"], "top")
            self.assertFalse(monitor.get("pendingReplenishment"))

    def test_low_usage_alone_or_shift_without_decrease_is_not_replenishment(self):
        for used, reset_at in (
            (0, None),
            (0, START + 86400),
            (0, START + 86400 - 1),
            (1, START + 2 * 86400),
        ):
            with self.subTest(used=used, reset_at=reset_at):
                self.assert_still_running(
                    run_window(reading(1, now=START + 30)),
                    [reading(used, now=now, reset_at=reset_at) for now in (START + 60, START + 81)],
                )

    def test_low_shift_needs_known_anchor_and_persistent_confirmation_evidence(self):
        shifted = START + 2 * 86400
        self.assert_still_running(
            run_window(reading(1, now=START + 30, reset_at=None), stop_on_renewal=False),
            [reading(0, now=now, reset_at=shifted) for now in (START + 60, START + 81)],
        )
        for reset_at in (None, START + 86400):
            monitor, _ = observe(
                run_window(reading(1, now=START + 30)),
                reading(0, now=START + 60, reset_at=shifted),
            )
            self.assert_still_running(monitor, [reading(0, now=START + 81, reset_at=reset_at)])

    def test_legacy_monitor_keeps_strong_decrease_requirement(self):
        monitor = run_window(reading(1, now=START + 30))
        del monitor["detectLowUsageRenewalShift"]
        self.assert_still_running(
            monitor,
            [reading(0, now=now, reset_at=START + 2 * 86400) for now in (START + 60, START + 81)],
        )


if __name__ == "__main__":
    unittest.main()

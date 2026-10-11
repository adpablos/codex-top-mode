import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from capacity_policy import action_decision, preflight, ready_work, validate_profile
from test_usage_monitor import START, reading

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/profile.example.json"


def profile():
    p = json.loads(EXAMPLE.read_text())
    p["authorization"].update(
        source="synthetic human authorization",
        approvedAt=START,
        validUntil=START + 86400,
        conditionalStart=True,
    )
    return p


def event(now=START + 30, suffix="announcement-1", mechanism="banked_reset", status="upcoming"):
    return {
        "sourceUrl": "https://example.org/official-capacity-news/" + suffix,
        "publishedAt": now,
        "mechanism": mechanism,
        "announcementStatus": status,
        "expectedResetAt": now + 3600,
        "verification": {"method": "primary_source_read", "verifiedAt": now},
    }


def start(p=None, e=None, current=None):
    return preflight(p or profile(), {}, current or reading(now=START + 30), e or event())


class ProfileTests(unittest.TestCase):
    def test_exported_example_is_disabled_and_requires_no_personal_system(self):
        p = json.loads(EXAMPLE.read_text())
        validate_profile(p)
        self.assertFalse(p["authorization"]["conditionalStart"])
        self.assertEqual(ready_work(p), ["document-recovery"])

    def test_new_banked_news_starts_only_preapproved_bounded_work(self):
        state, advice = start()
        self.assertEqual(advice["decision"], "start_window")
        self.assertEqual(advice["nextWork"], ["document-recovery"])
        self.assertEqual(state["usageMonitor"]["baseline"]["observedAt"], START + 30)
        self.assertEqual(advice["stopNewWorkAt"], START + 30 + 8 * 3600)
        self.assertNotIn("bankedStopAt", state["usageMonitor"])

    def test_authorization_expiry_caps_duration(self):
        p = profile()
        p["authorization"]["validUntil"] = START + 3600
        state, _ = start(p)
        self.assertEqual(state["usageMonitor"]["effectiveStopAt"], START + 3600)

    def test_disabled_or_expired_authority_remains_advisory(self):
        for change in ({"conditionalStart": False}, {"validUntil": START + 20}):
            p = profile()
            p["authorization"].update(change)
            state, advice = start(p)
            self.assertEqual(advice["decision"], "advisory_only")
            self.assertNotIn("usageMonitor", state)

    def test_old_future_or_unverified_posts_cannot_start(self):
        for change in (
            {"publishedAt": START},
            {"publishedAt": START + 31},
            {"verification": {"method": "snippet", "verifiedAt": START + 30}},
            {
                "verification": {
                    "method": "primary_source_read",
                    "verifiedAt": START + 31,
                }
            },
        ):
            e = event()
            e.update(change)
            state, advice = start(e=e)
            self.assertEqual(advice["decision"], "announcement_rejected")
            self.assertNotIn("usageMonitor", state)

    def test_discovery_does_not_relabel_an_old_publication(self):
        state, advice = start(current=reading(now=START + 30 + 8 * 3600 + 1))
        self.assertEqual(advice["decision"], "announcement_rejected")
        self.assertNotIn("usageMonitor", state)

    def test_unknown_mechanism_is_advisory(self):
        state, advice = start(e=event(mechanism="unspecified"))
        self.assertEqual(advice["decision"], "advisory_only")
        self.assertNotIn("usageMonitor", state)

    def test_applied_automatic_restoration_does_not_start(self):
        for mechanism in ("automatic_restoration", "mixed"):
            state, advice = start(e=event(mechanism=mechanism, status="applied"))
            self.assertEqual(advice["decision"], "advisory_only")
            self.assertNotIn("usageMonitor", state)
        state, advice = start(e=event(status="applied"))
        self.assertEqual(advice["decision"], "start_window")
        self.assertEqual(state["usageMonitor"]["baseline"]["availableResets"], 3)

    def test_unspecified_upcoming_can_be_explicitly_authorized(self):
        p = profile()
        p["authorization"]["allowUnspecifiedUpcoming"] = True
        _, advice = start(p, event(mechanism="unspecified"))
        self.assertEqual(advice["decision"], "start_window")
        _, advice = start(p, event(mechanism="unspecified", status="applied"))
        self.assertEqual(advice["decision"], "advisory_only")
        for expected in (START + 30, "2033-05-18T04:00:00"):
            e = event(mechanism="unspecified")
            e["expectedResetAt"] = expected
            _, advice = start(p, e)
            self.assertEqual(advice["decision"], "announcement_rejected")

    def test_verified_upcoming_news_can_start_without_an_exact_reset_time(self):
        for mechanism in (
            "banked_reset",
            "automatic_restoration",
            "mixed",
            "unspecified",
        ):
            for missing in (True, False):
                with self.subTest(mechanism=mechanism, missing=missing):
                    p = profile()
                    p["authorization"]["allowUnspecifiedUpcoming"] = True
                    e = event(mechanism=mechanism)
                    if missing:
                        del e["expectedResetAt"]
                    else:
                        e["expectedResetAt"] = None
                    state, advice = start(p, e)
                    self.assertEqual(advice["decision"], "start_window")
                    self.assertIsNone(state["usageMonitor"]["announcement"]["expectedResetAt"])
                    self.assertEqual(advice["stopNewWorkAt"], START + 30 + 8 * 3600)

    def test_explicit_reset_time_cannot_contradict_upcoming_news(self):
        for expected in (
            START + 29,
            START + 30,
            "2033-05-18T04:00:00",
            "unknown",
            True,
        ):
            with self.subTest(expected=expected):
                e = event()
                e["expectedResetAt"] = expected
                state, advice = start(e=e)
                self.assertEqual(advice["decision"], "announcement_rejected")
                self.assertNotIn("usageMonitor", state)

    def test_unknown_reset_time_does_not_promote_applied_or_unverified_news(self):
        for mechanism in ("automatic_restoration", "mixed", "unspecified"):
            p = profile()
            p["authorization"]["allowUnspecifiedUpcoming"] = True
            e = event(mechanism=mechanism, status="applied")
            e["expectedResetAt"] = None
            state, advice = start(p, e)
            self.assertEqual(advice["decision"], "advisory_only")
            self.assertNotIn("usageMonitor", state)
        for change in (
            {"announcementStatus": None},
            {"announcementStatus": "ambiguous"},
            {"verification": {"method": "secondary_summary", "verifiedAt": START + 30}},
            {"verification": {"method": "snippet", "verifiedAt": START + 30}},
        ):
            e = event()
            del e["expectedResetAt"]
            e.update(change)
            state, advice = start(e=e)
            self.assertEqual(advice["decision"], "announcement_rejected")
            self.assertNotIn("usageMonitor", state)

    def test_recurring_consent_until_revoked_preserves_eight_hour_deadline(self):
        p = profile()
        p["authorization"]["validUntil"] = None
        state, advice = start(p)
        deadline = START + 30 + 8 * 3600
        self.assertEqual(advice["stopNewWorkAt"], deadline)
        state, advice = preflight(p, state, reading(now=deadline))
        self.assertEqual(advice["decision"], "stop_new_work")
        state, advice = preflight(
            p,
            state,
            reading(now=deadline + 60),
            event(deadline + 60, "fresh-recurring-event"),
        )
        self.assertEqual(advice["decision"], "start_window")
        self.assertEqual(advice["stopNewWorkAt"], deadline + 60 + 8 * 3600)
        p["authorization"]["conditionalStart"] = False
        _, advice = preflight(p, state, reading(now=deadline + 90))
        self.assertEqual(advice["decision"], "stop_new_work")

    def test_confirmed_native_replenishment_blocks_earlier_unhandled_news(self):
        state, _ = start()
        state, _ = preflight(profile(), state, reading(0, now=START + 60))
        state, _ = preflight(profile(), state, reading(1, now=START + 81))
        _, advice = preflight(
            profile(),
            state,
            reading(1, now=START + 90),
            event(START + 50, "different-unhandled-news"),
        )
        self.assertEqual(advice["decision"], "advisory_only")
        self.assertIn("already confirmed", advice["reason"])
        _, advice = preflight(
            profile(),
            state,
            reading(1, now=START + 100),
            event(START + 100, "later-future-news"),
        )
        self.assertEqual(advice["decision"], "start_window")

    def test_authorized_publisher_cannot_be_spoofed_by_host_or_path(self):
        for url in (
            "https://example.org.attacker.invalid/official-capacity-news/a",
            "https://example.org/official-capacity-news-spoof/a",
            "https://example.org@attacker.invalid/official-capacity-news/a",
            "http://example.org/official-capacity-news/a",
        ):
            e = event()
            e["sourceUrl"] = url
            _, advice = start(e=e)
            self.assertEqual(advice["decision"], "announcement_rejected")

    def test_url_variants_never_extend_or_restart_a_window(self):
        state, advice = start()
        stop = advice["stopNewWorkAt"]
        e = event()
        e["sourceUrl"] += "?tracking=fictional#fragment"
        state, advice = preflight(profile(), state, reading(now=START + 60), e)
        self.assertEqual(advice["decision"], "continue_window")
        self.assertEqual(advice["announcementStatus"], "duplicate")
        self.assertEqual(advice["stopNewWorkAt"], stop)
        state, advice = preflight(profile(), state, reading(now=stop), e)
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["stopNewWorkAt"], stop)
        state, advice = preflight(profile(), state, reading(now=stop + 1), e)
        self.assertNotEqual(advice["decision"], "start_window")
        self.assertEqual(state["usageMonitor"]["mode"], "normal")

    def test_new_news_and_grants_during_work_do_not_extend_deadline(self):
        state, advice = start()
        stop = advice["stopNewWorkAt"]
        state, advice = preflight(
            profile(),
            state,
            reading(now=START + 60, resets=4, grants=[START + 40]),
            event(START + 50, "announcement-2"),
        )
        self.assertEqual(advice["announcementStatus"], "recorded_without_extending_window")
        self.assertEqual(advice["stopNewWorkAt"], stop)
        self.assertEqual(state["usageMonitor"]["mode"], "top")

    def test_second_new_post_after_completed_window_can_use_still_valid_authority(self):
        p = profile()
        p["limits"]["maximumHours"] = 1
        state, _ = start(p)
        state, advice = preflight(p, state, reading(now=START + 3630))
        self.assertEqual(advice["decision"], "stop_new_work")
        state, advice = preflight(
            p, state, reading(now=START + 3640), event(START + 3640, "announcement-2")
        )
        self.assertEqual(advice["decision"], "start_window")
        self.assertEqual(len(state["completedWindows"]), 1)
        self.assertEqual(state["usageMonitor"]["startedAt"], START + 3640)

    def test_new_announcement_when_expired_window_is_observed_is_not_consumed(self):
        p = profile()
        p["limits"]["maximumHours"] = 1
        state, first = start(p)
        now = first["stopNewWorkAt"] + 180
        state, advice = preflight(p, state, reading(now=now), event(now - 60, "announcement-2"))
        self.assertEqual(advice["decision"], "start_window")
        self.assertEqual(advice["announcementStatus"], "consumed")
        self.assertEqual(state["usageMonitor"]["startedAt"], now)
        self.assertEqual(state["completedWindows"][0]["stoppedAt"], first["stopNewWorkAt"])

    def test_busy_owners_do_not_hide_window_end_and_event_can_retry(self):
        p = profile()
        p["limits"]["maximumHours"] = 1
        state, first = start(p)
        for task in p["backlog"]:
            task["status"] = "in_progress"
        now = first["stopNewWorkAt"] + 180
        e = event(now - 60, "busy-window-end")
        state, advice = preflight(p, state, reading(now=now), e)
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "time_window_ended")
        self.assertEqual(advice["announcementStatus"], "preflight_blocked")
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(advice["mode"], "normal")
        self.assertEqual(advice["stopNewWorkAt"], first["stopNewWorkAt"])
        self.assertEqual(len(state["seenAnnouncementIds"]), 1)
        for task in p["backlog"]:
            task["status"] = "pending"
        state, advice = preflight(p, state, reading(now=now + 1), e)
        self.assertEqual(advice["decision"], "start_window")
        self.assertEqual(advice["announcementStatus"], "consumed")

    def test_revocation_stop_survives_an_advisory_event(self):
        p = profile()
        state, _ = start(p)
        p["authorization"]["conditionalStart"] = False
        state, advice = preflight(
            p, state, reading(now=START + 60), event(START + 50, "revoked-news")
        )
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "authorization_expired_or_changed")
        self.assertEqual(advice["announcementStatus"], "advisory_only")
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(state["usageMonitor"]["mode"], "normal")

    def test_replenishment_stop_survives_earlier_unhandled_news(self):
        p = profile()
        state, _ = start(p)
        state, _ = preflight(p, state, reading(0, now=START + 60))
        state, advice = preflight(
            p, state, reading(1, now=START + 81), event(START + 50, "earlier-news")
        )
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "quota_replenishment_confirmed")
        self.assertEqual(advice["announcementStatus"], "advisory_only")
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(state["usageMonitor"]["mode"], "normal")

    def test_window_end_survives_the_publication_replay_guard(self):
        p = profile()
        p["limits"]["maximumHours"] = 1
        state, first = start(p)
        e = event()
        e["sourceUrl"] += "/photo/1"
        e["expectedResetAt"] = None
        _, advice = preflight(p, state, reading(now=first["stopNewWorkAt"]), e)
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "time_window_ended")
        self.assertEqual(advice["announcementStatus"], "advisory_only")
        self.assertEqual(advice["nextWork"], [])

    def test_scheduled_renewal_is_advertised_as_the_earliest_stop(self):
        state, advice = start(current=reading(now=START + 30, reset_at=START + 7200))
        self.assertEqual(advice["stopNewWorkAt"], START + 7200)
        self.assertEqual(state["stopNewWorkAt"], START + 7200)
        self.assertEqual(state["usageMonitor"]["effectiveStopAt"], START + 30 + 8 * 3600)

    def test_unknown_renewal_still_requires_two_fresh_strong_drop_readings(self):
        p = profile()
        p["limits"]["stopOnScheduledWeeklyRenewal"] = False
        state, _ = start(p, current=reading(60, now=START + 30, reset_at=None))
        state, advice = preflight(p, state, reading(0, now=START + 60, reset_at=None))
        self.assertEqual(advice["reason"], "confirm_replenishment_with_fresh_read")
        state, stale = preflight(p, state, reading(0, now=START + 60, reset_at=None))
        self.assertEqual(stale["reason"], "stale_observation")
        state, advice = preflight(p, state, reading(1, now=START + 81, reset_at=None))
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "quota_replenishment_confirmed")
        self.assertEqual(advice["stopNewWorkAt"], START + 81)

    def test_x_media_and_host_aliases_cannot_replay_news(self):
        p = profile()
        p["sources"]["announcements"] = ["https://x.com/example_pub"]
        p["limits"]["maximumHours"] = 1
        e = event()
        e["sourceUrl"] = "https://x.com/example_pub/status/123"
        state, first = start(p, e)
        e["sourceUrl"] = "https://x.com/Example_Pub/status/123/photo/1?ref_src=fake"
        e["expectedResetAt"] = None
        state, advice = preflight(p, state, reading(now=START + 60), e)
        self.assertEqual(advice["announcementStatus"], "duplicate")
        state, _ = preflight(p, state, reading(now=first["stopNewWorkAt"]))
        state, advice = preflight(p, state, reading(now=first["stopNewWorkAt"] + 1), e)
        self.assertEqual(advice["decision"], "duplicate_announcement")
        self.assertEqual(state["usageMonitor"]["mode"], "normal")

    def test_ambiguous_source_path_segments_are_rejected(self):
        for suffix in ("../other/status/1", "%2e%2e/other/status/1", "//status/1"):
            e = event()
            e["sourceUrl"] = "https://example.org/official-capacity-news/" + suffix
            _, advice = start(e=e)
            self.assertEqual(advice["decision"], "announcement_rejected")

    def test_old_publication_with_a_different_url_cannot_restart(self):
        p = profile()
        p["limits"]["maximumHours"] = 1
        state, first = start(p)
        state, _ = preflight(p, state, reading(now=first["stopNewWorkAt"]))
        e = event()
        e["sourceUrl"] += "/photo/1"
        e["expectedResetAt"] = None
        state, advice = preflight(p, state, reading(now=first["stopNewWorkAt"] + 1), e)
        self.assertEqual(advice["decision"], "advisory_only")
        self.assertEqual(state["usageMonitor"]["mode"], "normal")

    def test_no_event_never_starts_work(self):
        state, advice = preflight(profile(), {}, reading(now=START + 30))
        self.assertEqual(advice["decision"], "no_announcement")
        self.assertNotIn("usageMonitor", state)

    def test_missing_or_exhausted_usage_blocks_then_allows_fresh_preflight(self):
        for current in (
            reading(100, now=START + 30),
            {
                "observedAt": START + 30,
                "windows": [],
                "availableResets": None,
                "grantTimes": [],
            },
        ):
            state, advice = start(current=current)
            self.assertEqual(advice["decision"], "preflight_blocked")
            self.assertNotIn("usageMonitor", state)
            state, advice = preflight(profile(), state, reading(now=START + 60), event())
            self.assertEqual(advice["decision"], "start_window")

    def test_low_usage_does_not_prove_restoration_or_veto_future_work(self):
        _, advice = start(current=reading(1, now=START + 30))
        self.assertEqual(advice["decision"], "start_window")

    def test_expired_native_renewal_blocks_start(self):
        _, advice = start(current=reading(now=START + 30, reset_at=START + 20))
        self.assertEqual(advice["decision"], "preflight_blocked")

    def test_missing_renewal_blocks_only_policy_that_requires_it(self):
        current = reading(now=START + 30, reset_at=None)
        _, advice = start(current=current)
        self.assertEqual(advice["decision"], "preflight_blocked")
        p = profile()
        p["limits"]["stopOnScheduledWeeklyRenewal"] = False
        _, advice = start(p, current=current)
        self.assertEqual(advice["decision"], "start_window")

    def test_scheduled_stop_holds_even_if_later_telemetry_is_missing(self):
        state, _ = start(current=reading(now=START + 30, reset_at=START + 90))
        current = {
            "observedAt": START + 100,
            "windows": [],
            "availableResets": None,
            "grantTimes": [],
        }
        state, advice = preflight(profile(), state, current)
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "scheduled_weekly_renewal_due")
        self.assertEqual(advice["stopNewWorkAt"], START + 90)

    def test_earlier_absolute_stop_wins_over_scheduled_renewal(self):
        state, advice = start()
        stop = advice["stopNewWorkAt"]
        state, advice = preflight(profile(), state, reading(now=START + 86401))
        self.assertEqual(advice["stopNewWorkAt"], stop)
        self.assertEqual(advice["reason"], "time_window_ended")

    def test_off_schedule_stop_keeps_existing_two_fresh_read_gate(self):
        state, _ = start()
        state, advice = preflight(profile(), state, reading(0, now=START + 60))
        self.assertEqual(advice["reason"], "confirm_replenishment_with_fresh_read")
        state, advice = preflight(profile(), state, reading(1, now=START + 81))
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "quota_replenishment_confirmed")

    def test_low_usage_shift_requires_two_fresh_reads_before_stopping(self):
        state, _ = start(current=reading(1, now=START + 30))
        shifted = START + 2 * 86400
        state, advice = preflight(profile(), state, reading(0, now=START + 60, reset_at=shifted))
        self.assertEqual(advice["decision"], "continue_window")
        self.assertEqual(advice["reason"], "confirm_replenishment_with_fresh_read")
        self.assertEqual(state["usageMonitor"]["mode"], "top")
        state, advice = preflight(profile(), state, reading(0, now=START + 70, reset_at=shifted))
        self.assertEqual(state["usageMonitor"]["mode"], "top")
        state, advice = preflight(profile(), state, reading(0, now=START + 81, reset_at=shifted))
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["reason"], "quota_replenishment_confirmed")
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(advice["stopNewWorkAt"], START + 81)

    def test_low_usage_alone_or_shift_without_decrease_is_not_replenishment(self):
        for used, reset_at in (
            (0, None),
            (0, START + 86400),
            (0, START + 86400 - 1),
            (1, START + 2 * 86400),
        ):
            with self.subTest(used=used, reset_at=reset_at):
                state, _ = start(current=reading(1, now=START + 30))
                for now in (START + 60, START + 81):
                    state, advice = preflight(
                        profile(), state, reading(used, now=now, reset_at=reset_at)
                    )
                    self.assertEqual(advice["decision"], "continue_window")
                    self.assertFalse(state["usageMonitor"].get("pendingReplenishment"))

    def test_low_shift_needs_known_anchor_and_persistent_confirmation_evidence(self):
        p = profile()
        p["limits"]["stopOnScheduledWeeklyRenewal"] = False
        state, _ = start(p, current=reading(1, now=START + 30, reset_at=None))
        for now in (START + 60, START + 81):
            state, advice = preflight(p, state, reading(0, now=now, reset_at=START + 2 * 86400))
            self.assertEqual(advice["decision"], "continue_window")
            self.assertFalse(state["usageMonitor"].get("pendingReplenishment"))
        for reset_at in (None, START + 86400):
            state, _ = start(current=reading(1, now=START + 30))
            state, _ = preflight(
                profile(),
                state,
                reading(0, now=START + 60, reset_at=START + 2 * 86400),
            )
            state, advice = preflight(
                profile(), state, reading(0, now=START + 81, reset_at=reset_at)
            )
            self.assertEqual(advice["decision"], "continue_window")
            self.assertFalse(state["usageMonitor"].get("pendingReplenishment"))

    def test_legacy_monitor_keeps_strong_decrease_requirement(self):
        state, _ = start(current=reading(1, now=START + 30))
        del state["usageMonitor"]["detectLowUsageRenewalShift"]
        for now in (START + 60, START + 81):
            state, advice = preflight(
                profile(),
                state,
                reading(0, now=now, reset_at=START + 2 * 86400),
            )
            self.assertEqual(advice["decision"], "continue_window")
            self.assertFalse(state["usageMonitor"].get("pendingReplenishment"))

    def test_policy_change_stops_without_reauthorizing_old_news(self):
        state, _ = start()
        p = profile()
        p["limits"]["maximumHours"] = 10
        state, advice = preflight(p, state, reading(now=START + 60), event())
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(state["usageMonitor"]["stopReason"], "authorization_expired_or_changed")
        _, advice = preflight(p, state, reading(now=START + 61), event())
        self.assertEqual(advice["decision"], "duplicate_announcement")

    def test_backlog_refresh_does_not_change_frozen_authority(self):
        state, advice = start()
        stop = advice["stopNewWorkAt"]
        p = profile()
        p["backlog"][0]["status"] = "done"
        state, advice = preflight(p, state, reading(now=START + 60))
        self.assertEqual(advice["decision"], "continue_window")
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(advice["stopNewWorkAt"], stop)

    def test_action_policy_preserves_exclusions_and_separate_review_merge_gates(self):
        p = profile()
        self.assertEqual(action_decision(p, "sample-notes", "edit"), "allowed")
        for action in ("review", "merge", "redeem_reset"):
            self.assertEqual(action_decision(p, "sample-notes", action), "ask")
        self.assertEqual(action_decision(p, "client-example", "edit"), "deny")
        self.assertEqual(action_decision(p, "unregistered", "edit"), "deny")
        self.assertEqual(action_decision(p, "sample-notes", "unknown"), "deny")
        p["actions"]["redeem_reset"] = "allowed"
        with self.assertRaises(ValueError):
            validate_profile(p)

    def test_busy_owners_and_active_slots_cannot_be_reassigned(self):
        p = profile()
        task = copy.deepcopy(p["backlog"][0])
        task.update(id="another-task", owner="second-owner", priority=2)
        p["backlog"].append(task)
        p["backlog"][0]["status"] = "in_progress"
        self.assertEqual(ready_work(p), ["another-task"])
        p["limits"]["maximumActiveThreads"] = 1
        self.assertEqual(ready_work(p), [])
        _, advice = start(p)
        self.assertEqual(advice["decision"], "preflight_blocked")

    def test_each_active_task_counts_even_with_a_shared_owner(self):
        p = profile()
        p["backlog"][0]["status"] = "in_progress"
        second = copy.deepcopy(p["backlog"][0])
        second["id"] = "second-active-task"
        p["backlog"].append(second)
        pending = copy.deepcopy(second)
        pending.update(id="pending-task", status="pending", owner="another-owner")
        p["backlog"].append(pending)
        self.assertEqual(ready_work(p), [])
        _, advice = start(p)
        self.assertEqual(advice["decision"], "preflight_blocked")

    def test_short_quota_exhaustion_pauses_assignments_without_extending_window(self):
        state, advice = start()
        stop = advice["stopNewWorkAt"]
        current = reading(now=START + 60)
        current["windows"].append(
            {
                "usedPercent": 100,
                "durationMinutes": 300,
                "resetsAt": START + 300,
                "slot": "secondary",
            }
        )
        state, advice = preflight(profile(), state, current)
        self.assertEqual(advice["decision"], "wait_for_capacity")
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(advice["stopNewWorkAt"], stop)
        state, advice = preflight(profile(), state, reading(now=START + 300))
        self.assertEqual(advice["decision"], "continue_window")
        self.assertEqual(advice["nextWork"], ["document-recovery"])
        self.assertEqual(advice["stopNewWorkAt"], stop)

    def test_stale_poll_cannot_offer_work_or_rewind_last_update(self):
        state, _ = start()
        state, advice = preflight(profile(), state, reading(now=START + 30))
        self.assertEqual(advice["decision"], "wait_for_capacity")
        self.assertEqual(advice["nextWork"], [])
        state, _ = preflight(profile(), state, reading(now=START + 60))
        state, advice = preflight(profile(), state, reading(now=START + 40))
        self.assertEqual(advice["nextWork"], [])
        self.assertEqual(state["lastUpdatedAt"], START + 60)

    def test_invalid_public_event_does_not_obscure_required_stop(self):
        state, _ = start(current=reading(now=START + 30, reset_at=START + 90))
        state, advice = preflight(
            profile(), state, reading(now=START + 100), {"coverage": "unknown"}
        )
        self.assertEqual(advice["decision"], "stop_new_work")
        self.assertEqual(advice["stopNewWorkAt"], START + 90)

    def test_unready_blocked_and_finished_tasks_do_not_become_busywork(self):
        for change in (
            {"ready": False},
            {"blocker": "awaiting sample input"},
            {"status": "done"},
        ):
            p = profile()
            p["backlog"][0].update(change)
            self.assertEqual(ready_work(p), [])
            state, advice = start(p)
            self.assertEqual(advice["decision"], "preflight_blocked")
            self.assertNotIn("usageMonitor", state)

    def test_invalid_profile_does_not_mutate_state(self):
        for change in (
            {"approvedAt": "2033-05-18T00:00:00"},
            {"conditionalStart": "yes"},
        ):
            p = profile()
            p["authorization"].update(change)
            original = {"sentinel": "unchanged"}
            with self.assertRaises(ValueError):
                preflight(p, original, reading(), event())
            self.assertEqual(original, {"sentinel": "unchanged"})
        p = profile()
        del p["backlog"][0]["blocker"]
        with self.assertRaises(ValueError):
            validate_profile(p)

    def test_cli_creates_private_state_without_account_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "profile.json").write_text(json.dumps(profile()))
            (folder / "event.json").write_text(json.dumps(event()))
            payload = {
                "accountId": "synthetic-forbidden-account",
                "rateLimits": {
                    "primary": {
                        "usedPercent": 17,
                        "windowDurationMins": 10080,
                        "resetsAt": START + 86400,
                    }
                },
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("capacity_policy.py")),
                    "--profile",
                    str(folder / "profile.json"),
                    "--state",
                    str(folder / "state.json"),
                    "--event",
                    str(folder / "event.json"),
                    "--observed-at",
                    str(START + 30),
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            # CLI observation times use explicit ISO; numeric-looking strings are not timestamps.
            self.assertEqual(result.returncode, 2)
            self.assertFalse((folder / "state.json").exists())
            command = [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("capacity_policy.py")),
                "--profile",
                str(folder / "profile.json"),
                "--state",
                str(folder / "state.json"),
                "--event",
                str(folder / "event.json"),
                "--observed-at",
                "2033-05-18T03:33:50Z",
            ]
            result = subprocess.run(
                command,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["decision"], "start_window")
            self.assertEqual(os.stat(folder / "state.json").st_mode & 0o777, 0o600)
            self.assertNotIn("synthetic-forbidden-account", (folder / "state.json").read_text())
            self.assertNotIn("accountId", (folder / "state.json").read_text())


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from usage_monitor import epoch
from usage_report import (
    advise,
    agent_home,
    claude_tokens,
    codex_quota,
    codex_tokens,
    file_quota,
    markdown,
)

NOW = epoch("2033-05-18T12:00:00Z")
SINCE = epoch("2033-05-18T00:00:00Z")


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    os.utime(path, (NOW, NOW))


def usage(total, output=10):
    return {
        "input_tokens": total - output,
        "cached_input_tokens": total // 2,
        "output_tokens": output,
        "reasoning_output_tokens": 1,
        "total_tokens": total,
    }


def codex_rows(stamp="2033-05-18T01:00:00Z"):
    return [
        {"type": "session_meta", "payload": {"id": "private-session-id"}},
        {"type": "turn_context", "payload": {"model": "model-a", "effort": "high"}},
        {
            "timestamp": stamp,
            "type": "token_usage_record",
            "payload": {"response_id": "r1", "usage": usage(100)},
        },
        # The same response logged twice counts once.
        {
            "timestamp": stamp,
            "type": "token_usage_record",
            "payload": {"response_id": "r1", "usage": usage(100)},
        },
        {"type": "turn_context", "payload": {"model": "model-b", "effort": "low"}},
        {
            "timestamp": "2033-05-18T02:00:00Z",
            "type": "token_usage_record",
            "payload": {"response_id": "r2", "usage": usage(40)},
        },
        {
            "timestamp": "2033-05-18T02:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "primary": {
                        "used_percent": 40.0,
                        "window_minutes": 10080,
                        "resets_at": NOW + 10 * 3600,
                    },
                    "credits": {"balance": "secret-balance"},
                },
            },
        },
    ]


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_codex_usage_is_grouped_by_model_and_deduplicated(self):
        write_lines(self.home / "sessions/2033/05/18/rollout-x.jsonl", codex_rows())
        result = codex_tokens(self.home, SINCE, NOW)
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(result["responses"], 2)
        self.assertEqual(result["totalTokens"], 140)
        self.assertEqual(
            [(m["model"], m["effort"], m["total_tokens"]) for m in result["byModel"]],
            [("model-a", "high", 100), ("model-b", "low", 40)],
        )
        self.assertNotIn("private-session-id", json.dumps(result))

    def test_codex_usage_outside_the_window_is_ignored(self):
        write_lines(
            self.home / "sessions/rollout-old.jsonl",
            codex_rows(stamp="2033-05-17T23:00:00Z"),
        )
        result = codex_tokens(self.home, SINCE, NOW)
        self.assertEqual(result["totalTokens"], 40)

    def test_older_codex_logs_use_cumulative_counter_deltas(self):
        rows = [{"type": "turn_context", "payload": {"model": "model-a"}}]
        for stamp, total in (
            ("2033-05-17T23:00:00Z", 50),
            ("2033-05-18T01:00:00Z", 80),
            ("2033-05-18T02:00:00Z", 80),
            ("2033-05-18T03:00:00Z", 120),
        ):
            rows.append(
                {
                    "timestamp": stamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": usage(total)},
                    },
                }
            )
        write_lines(self.home / "sessions/rollout-legacy.jsonl", rows)
        result = codex_tokens(self.home, SINCE, NOW)
        self.assertEqual(result["totalTokens"], 70)
        self.assertEqual(result["responses"], 2)

    def test_older_codex_logs_are_flagged_as_a_possible_lower_bound(self):
        write_lines(self.home / "sessions/rollout-new.jsonl", codex_rows())
        self.assertEqual(codex_tokens(self.home, SINCE, NOW)["olderLogs"], 0)
        older = [
            {"type": "turn_context", "payload": {"model": "model-a"}},
            {"type": "compacted", "payload": {"message": "summary"}},
            {
                "timestamp": "2033-05-18T01:00:00Z",
                "type": "event_msg",
                "payload": {"type": "token_count", "info": {"total_token_usage": usage(50)}},
            },
        ]
        write_lines(self.home / "sessions/rollout-older.jsonl", older)
        # A log that has not logged any usage yet is not evidence of either format.
        write_lines(self.home / "sessions/rollout-empty.jsonl", older[:1])
        result = codex_tokens(self.home, SINCE, NOW)
        self.assertEqual((result["sessions"], result["olderLogs"]), (2, 1))
        report = {"since": "s", "until": "u", "providers": [result]}
        self.assertIn("1 of its logs in this interval use an older format", markdown(report))

    def test_claude_messages_count_once_and_skip_synthetic(self):
        def message(key, model="claude-x", stamp="2033-05-18T01:00:00Z"):
            return {
                "type": "assistant",
                "timestamp": stamp,
                "sessionId": "private-session",
                "message": {
                    "id": key,
                    "model": model,
                    "usage": {
                        "input_tokens": 1,
                        "cache_creation_input_tokens": 10,
                        "cache_read_input_tokens": 100,
                        "output_tokens": 5,
                    },
                },
            }

        write_lines(
            self.home / "projects/p/session.jsonl",
            [message("m1"), message("m1"), message("m2", "<synthetic>")],
        )
        write_lines(
            self.home / "projects/p/session/subagents/agent.jsonl",
            [
                {**message("m3", "claude-y"), "agentId": "worker"},
                message("m4", stamp="2033-05-17T01:00:00Z"),
            ],
        )
        result = claude_tokens(self.home, SINCE, NOW)
        self.assertEqual(result["responses"], 2)
        # The subagent keeps its parent's sessionId but is a session of its own.
        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["totalTokens"], 232)
        self.assertEqual({m["model"] for m in result["byModel"]}, {"claude-x", "claude-y"})
        self.assertNotIn("private-session", json.dumps(result))


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_codex_quota_comes_from_the_latest_log_reading(self):
        path = self.home / "sessions/rollout-x.jsonl"
        write_lines(path, codex_rows())
        reading = codex_quota(self.home, NOW)
        self.assertEqual(reading["windows"][0]["usedPercent"], 40.0)
        self.assertNotIn("secret-balance", json.dumps(reading))
        advice = advise(reading, epoch("2033-05-18T03:00:00Z"))
        self.assertEqual(advice["suggestion"], "consider_top_mode")
        self.assertEqual(advice["reasons"], ["unused_weekly_quota_before_reset"])
        self.assertEqual(advice["hoursToWeeklyReset"], 19.0)
        self.assertEqual(advise(reading, NOW)["reasons"][0], "reading_is_stale")

    def test_codex_quota_ignores_model_specific_buckets(self):
        def limits_row(stamp, used, limit_id):
            window = {"used_percent": used, "window_minutes": 10080, "resets_at": NOW + 3600}
            limits = {"primary": window}
            if limit_id:
                limits["limit_id"] = limit_id
            payload = {"type": "token_count", "rate_limits": limits}
            return {"timestamp": stamp, "type": "event_msg", "payload": payload}

        rows = [
            limits_row("2033-05-18T01:00:00Z", 10, None),  # legacy row without an id
            limits_row("2033-05-18T02:00:00Z", 20, "codex"),
            limits_row("2033-05-18T03:00:00Z", 99, "codex_other_model"),
        ]
        write_lines(self.home / "sessions/rollout-x.jsonl", rows)
        reading = codex_quota(self.home, NOW)
        self.assertEqual(reading["windows"][0]["usedPercent"], 20.0)
        write_lines(self.home / "sessions/rollout-x.jsonl", rows[:1] + rows[2:])
        self.assertEqual(codex_quota(self.home, NOW)["windows"][0]["usedPercent"], 10.0)

    def test_a_capture_time_in_the_future_is_not_a_fresh_reading(self):
        path = self.home / "status.json"
        limits = {"seven_day": {"used_percentage": 40, "resets_at": NOW + 10 * 3600}}
        for ahead, suggestion in ((300, "consider_top_mode"), (301, "refresh_or_wait")):
            with self.subTest(ahead=ahead):
                reading = {"observedAt": NOW + ahead, "payload": {"rate_limits": limits}}
                path.write_text(json.dumps(reading))
                self.assertEqual(advise(file_quota(path), NOW)["suggestion"], suggestion)

    def test_a_reading_from_before_its_weekly_renewal_needs_a_fresh_one(self):
        path = self.home / "status.json"
        for resets_in, suggestion in ((3600, "consider_top_mode"), (0, "refresh_or_wait")):
            with self.subTest(resets_in=resets_in):
                limits = {"seven_day": {"used_percentage": 40, "resets_at": NOW + resets_in}}
                reading = {"observedAt": NOW - 3600, "payload": {"rate_limits": limits}}
                path.write_text(json.dumps(reading))
                advice = advise(file_quota(path), NOW)
                self.assertEqual(advice["suggestion"], suggestion)

    def test_a_reading_without_a_weekly_window_is_unknown(self):
        path = self.home / "five-hour-only.json"
        limits = {"five_hour": {"used_percentage": 10, "resets_at": NOW + 3600}}
        path.write_text(json.dumps({"observedAt": NOW, "payload": {"rate_limits": limits}}))
        advice = advise(file_quota(path), NOW)
        self.assertEqual(advice["suggestion"], "unknown")
        self.assertEqual(advice["reasons"], ["weekly_window_unknown"])

    def test_codex_quota_is_the_newest_reading_not_the_newest_file(self):
        def quota_row(stamp, used):
            limits = {"primary": {"used_percent": used, "window_minutes": 10080}}
            return {"timestamp": stamp, "payload": {"rate_limits": limits}}

        # A long session still logging today, whose only reading is days old.
        old = self.home / "sessions/2033/05/15/rollout-old.jsonl"
        write_lines(old, [quota_row("2033-05-15T08:00:00Z", 7), {"type": "turn_context"}])
        # The newest reading's session was archived meanwhile.
        fresh = self.home / "archived_sessions/rollout-new.jsonl"
        write_lines(fresh, [quota_row("2033-05-18T11:55:00Z", 4)])
        os.utime(fresh, (NOW - 300, NOW - 300))
        stale = self.home / "sessions/2033/05/18/rollout-earlier.jsonl"
        write_lines(stale, [quota_row("2033-05-18T09:00:00Z", 3)])
        os.utime(stale, (NOW - 3 * 3600, NOW - 3 * 3600))
        reading = codex_quota(self.home, NOW)
        self.assertEqual(reading["observedAt"], "2033-05-18T11:55:00Z")
        self.assertEqual(reading["windows"][0]["usedPercent"], 4.0)

    def test_claude_status_line_reading_carries_its_capture_time(self):
        status = {
            "rate_limits": {
                "five_hour": {"used_percentage": 20, "resets_at": NOW + 3600},
                "seven_day": {"used_percentage": 90, "resets_at": NOW + 3600},
            }
        }
        path = self.home / "status.json"
        path.write_text(json.dumps({"observedAt": NOW - 3600, "payload": status}))
        advice = advise(file_quota(path), NOW)
        self.assertEqual(advice["weeklyUsedPercent"], 90)
        self.assertEqual(advice["readingAgeHours"], 1.0)
        self.assertEqual(advice["suggestion"], "nothing_to_do")
        # A bare reading says nothing about when it was taken; the file time is
        # not evidence because copying or restoring the file changes it.
        path.write_text(json.dumps(status))
        with self.assertRaises(ValueError):
            file_quota(path)
        reading = file_quota(path, "2033-05-18T11:00:00Z")
        self.assertEqual(epoch(reading["observedAt"]), NOW - 3600)

    def test_stale_or_exhausted_readings_do_not_suggest_work(self):
        week = {"slot": "primary", "durationMinutes": 10080, "resetsAt": NOW + 3600}
        base = {"source": "test", "availableResets": None, "resetExpirations": []}
        stale = {**base, "observedAt": NOW - 7 * 3600, "windows": [{**week, "usedPercent": 10}]}
        full = {**base, "observedAt": NOW, "windows": [{**week, "usedPercent": 100}]}
        self.assertEqual(advise(stale, NOW)["suggestion"], "refresh_or_wait")
        self.assertEqual(advise(full, NOW)["reasons"], ["weekly_limit_reached"])
        self.assertEqual(advise(None, NOW)["suggestion"], "unknown")

    def test_expiring_saved_resets_are_suggested(self):
        payload = {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": 90,
                        "windowDurationMins": 10080,
                        "resetsAt": NOW + 5 * 86400,
                    }
                }
            },
            "rateLimitResetCredits": {
                "availableCount": 1,
                "credits": [{"status": "available", "expiresAt": NOW + 2 * 86400}],
            },
        }
        path = self.home / "payload.json"
        path.write_text(json.dumps(payload))
        advice = advise(file_quota(path, "2033-05-18T12:00:00Z"), NOW)
        self.assertEqual(advice["reasons"], ["saved_resets_expiring_soon"])
        self.assertEqual(advice["suggestion"], "consider_top_mode")

    def test_agent_folders_follow_their_environment_overrides(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            self.assertEqual(agent_home("CODEX_HOME", ".codex"), self.home)
        with patch.dict(os.environ, {"CODEX_HOME": ""}):
            self.assertEqual(agent_home("CODEX_HOME", ".codex"), Path.home() / ".codex")

    def test_cli_prints_counts_without_private_text(self):
        write_lines(self.home / "sessions/rollout-x.jsonl", codex_rows())
        script = Path(__file__).with_name("usage_report.py")
        output = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "tokens",
                "--since",
                "2033-05-18T00:00:00Z",
                "--until",
                "2033-05-18T12:00:00Z",
                "--markdown",
                "--codex-home",
                str(self.home),
                "--claude-home",
                str(self.home / "none"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("| codex | model-a | high | 1 | 100 |", output)
        self.assertNotIn(str(self.home), output)


if __name__ == "__main__":
    unittest.main()

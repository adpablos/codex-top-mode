import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from usage_monitor import epoch
from usage_report import advise, claude_tokens, codex_quota, codex_tokens, file_quota

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
            [message("m3", "claude-y"), message("m4", stamp="2033-05-17T01:00:00Z")],
        )
        result = claude_tokens(self.home, SINCE, NOW)
        self.assertEqual(result["responses"], 2)
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

    def test_claude_status_line_reading(self):
        path = self.home / "status.json"
        path.write_text(
            json.dumps(
                {
                    "rate_limits": {
                        "five_hour": {"used_percentage": 20, "resets_at": NOW + 3600},
                        "seven_day": {"used_percentage": 90, "resets_at": NOW + 3600},
                    }
                }
            )
        )
        reading = file_quota(path, "2033-05-18T11:00:00Z")
        advice = advise(reading, NOW)
        self.assertEqual(advice["weeklyUsedPercent"], 90)
        self.assertEqual(advice["suggestion"], "nothing_to_do")

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

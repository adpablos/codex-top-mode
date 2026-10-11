import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import usage_report
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
REPORT = {"since": "s", "until": "u"}


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
            # Cache writes are part of input, like cached input.
            "payload": {"response_id": "r2", "usage": {**usage(40), "cache_write_input_tokens": 7}},
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
        self.assertEqual(result["byModel"][1]["cache_write_input_tokens"], 7)
        self.assertIn("cache write input 7", markdown({**REPORT, "providers": [result]}))
        self.assertNotIn("private-session-id", json.dumps(result))

    def test_compressed_codex_logs_are_counted_as_unread(self):
        write_lines(self.home / "sessions/rollout-x.jsonl", codex_rows())
        self.assertEqual(codex_tokens(self.home, SINCE, NOW)["compressedLogs"], 0)
        names = (
            ("recent", NOW),
            ("earlier", SINCE - 1),
            # Started after the interval: its name says so, beyond any UTC offset.
            ("2033-05-19T02-00-01-id", NOW),
            # Within 14 hours of its end, an offset could put it inside: counted.
            ("2033-05-19T01-59-59-id", NOW),
        )
        for name, modified in names:
            path = self.home / f"archived_sessions/rollout-{name}.jsonl.zst"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x28\xb5\x2f\xfd")
            os.utime(path, (modified, modified))
        result = codex_tokens(self.home, SINCE, NOW)
        self.assertEqual((result["compressedLogs"], result["totalTokens"]), (2, 140))
        report = markdown({**REPORT, "providers": [result]})
        self.assertIn("2 compressed logs that may cover this interval were not read", report)

    def test_a_forked_codex_log_counts_only_its_own_responses(self):
        def record(response, thread, stamp="2033-05-18T03:00:00Z"):
            payload = {"response_id": response, "thread_id": thread, "usage": usage(100)}
            return {"timestamp": stamp, "type": "token_usage_record", "payload": payload}

        parent = [
            {"type": "session_meta", "payload": {"id": "parent"}},
            record("r1", "parent", "2033-05-17T23:00:00Z"),
            record("r2", "parent"),
        ]
        # A fork copies its parent's history, with new timestamps, then adds its own.
        child = [
            {"type": "session_meta", "payload": {"id": "child"}},
            *[{**row, "timestamp": "2033-05-18T04:00:00Z"} for row in parent],
            record("r3", "child"),
        ]
        # A thread that writes a second log of its own repeats its records.
        rewritten = [*parent, record("r4", "parent")]
        write_lines(self.home / "sessions/rollout-parent.jsonl", [*parent, record("r5", "parent")])
        write_lines(self.home / "sessions/rollout-child.jsonl", child)
        write_lines(self.home / "sessions/rollout-parent_2.jsonl", rewritten)
        result = codex_tokens(self.home, SINCE, NOW)
        # r1 is before the interval; r2 to r5 count once each.
        self.assertEqual((result["responses"], result["totalTokens"]), (4, 400))
        # Both of the parent's logs add usage, but it is one thread.
        self.assertEqual(result["sessions"], 2)

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
        # Only logs that add usage to the interval count: not one with no usage yet,
        # nor one whose older-format usage all comes before the interval.
        write_lines(self.home / "sessions/rollout-empty.jsonl", older[:1])
        earlier = [*older[:2], {**older[2], "timestamp": "2033-05-17T23:00:00Z"}]
        write_lines(self.home / "sessions/rollout-earlier.jsonl", earlier)
        result = codex_tokens(self.home, SINCE, NOW)
        self.assertEqual((result["sessions"], result["olderLogs"]), (2, 1))
        report = {**REPORT, "providers": [result]}
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
                    "stop_reason": "end_turn",
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
        self.assertEqual(result["unfinishedResponses"], 0)
        self.assertNotIn("private-session", json.dumps(result))

    def test_claude_responses_use_their_finished_copy(self):
        def row(key, stop_reason, output):
            usage = {"input_tokens": 10, "output_tokens": output}
            message = {"id": key, "model": "claude-x", "stop_reason": stop_reason, "usage": usage}
            return {"type": "assistant", "timestamp": "2033-05-18T01:00:00Z", "message": message}

        # A response logged while streaming, then finished; and one never finished.
        rows = [row("m1", None, 1), row("m1", "end_turn", 500), row("m1", None, 1)]
        rows += [row("m2", None, 1), row("m2", None, 40)]
        write_lines(self.home / "projects/p/session/subagents/agent.jsonl", rows)
        result = claude_tokens(self.home, SINCE, NOW)
        self.assertEqual((result["responses"], result["totalTokens"]), (2, 560))
        self.assertEqual(result["unfinishedResponses"], 1)
        report = markdown({**REPORT, "providers": [result]})
        self.assertIn("1 of its responses were logged before they finished", report)

    def test_claude_advisor_steps_count_under_the_advisor_model(self):
        step = {"input_tokens": 1, "cache_read_input_tokens": 100, "output_tokens": 5}
        advisor = {"model": "claude-advisor", "input_tokens": 800, "output_tokens": 200}
        steps = [{"type": "message", **step}, {"type": "advisor_message", **advisor}]
        # The top-level counts cover only the executor's steps.
        executor = {"input_tokens": 2, "cache_read_input_tokens": 200, "output_tokens": 10}
        usage = {**executor, "iterations": [*steps, {"type": "message", **step}]}
        row = {
            "type": "assistant",
            "timestamp": "2033-05-18T01:00:00Z",
            "effort": "low",
            "message": {"id": "m1", "model": "claude-x", "usage": usage},
        }
        write_lines(self.home / "projects/p/session.jsonl", [row])
        result = claude_tokens(self.home, SINCE, NOW)
        self.assertEqual((result["responses"], result["totalTokens"]), (1, 1212))
        models = {(m["model"], m["effort"]): m for m in result["byModel"]}
        self.assertEqual(models["claude-x", "low"]["total_tokens"], 212)
        self.assertEqual(models["claude-advisor", None]["total_tokens"], 1000)
        self.assertEqual(models["claude-advisor", None]["responses"], 1)


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_codex_quota_comes_from_the_latest_log_reading(self):
        path = self.home / "sessions/rollout-x.jsonl"
        write_lines(path, codex_rows())
        reading = codex_quota(self.home)
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
        reading = codex_quota(self.home)
        self.assertEqual(reading["windows"][0]["usedPercent"], 20.0)
        write_lines(self.home / "sessions/rollout-x.jsonl", rows[:1] + rows[2:])
        self.assertEqual(codex_quota(self.home)["windows"][0]["usedPercent"], 10.0)

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

    def test_decisions_use_exact_times_not_rounded_ones(self):
        path = self.home / "status.json"
        cases = (
            (6 * 3600, 3600, "consider_top_mode"),
            (6 * 3600 + 60, 3600, "refresh_or_wait"),  # stale, though 6.0 h rounded
            (3600, 60, "consider_top_mode"),  # renews in a minute, not yet renewed
        )
        for age, resets_in, suggestion in cases:
            with self.subTest(age=age, resets_in=resets_in):
                limits = {"seven_day": {"used_percentage": 40, "resets_at": NOW + resets_in}}
                reading = {"observedAt": NOW - age, "payload": {"rate_limits": limits}}
                path.write_text(json.dumps(reading))
                self.assertEqual(advise(file_quota(path), NOW)["suggestion"], suggestion)

    def test_a_reading_without_a_weekly_window_is_unknown(self):
        path = self.home / "status.json"
        five_hour = {"five_hour": {"used_percentage": 10, "resets_at": NOW + 3600}}
        not_a_number = {"seven_day": {"used_percentage": True, "resets_at": NOW + 3600}}
        for limits in (five_hour, not_a_number):
            with self.subTest(limits=limits):
                reading = {"observedAt": NOW, "payload": {"rate_limits": limits}}
                path.write_text(json.dumps(reading))
                advice = advise(file_quota(path), NOW)
                self.assertEqual(advice["suggestion"], "unknown")
                self.assertEqual(advice["reasons"], ["weekly_window_unknown"])

    def test_an_old_codex_reading_is_stale_not_missing(self):
        limits = {"primary": {"used_percent": 40, "window_minutes": 10080}}
        row = {"timestamp": "2033-04-18T12:00:00Z", "payload": {"rate_limits": limits}}
        path = self.home / "sessions/2033/04/18/rollout-x.jsonl"
        write_lines(path, [row])
        os.utime(path, (NOW - 30 * 86400, NOW - 30 * 86400))
        advice = advise(codex_quota(self.home), NOW)
        self.assertEqual(advice["suggestion"], "refresh_or_wait")
        self.assertIn("reading_is_stale", advice["reasons"])

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
        reading = codex_quota(self.home)
        self.assertEqual(reading["observedAt"], "2033-05-18T11:55:00Z")
        self.assertEqual(reading["windows"][0]["usedPercent"], 4.0)

    def test_a_subagent_copy_of_old_readings_is_not_a_new_reading(self):
        def quota_row(stamp, used):
            limits = {"primary": {"used_percent": used, "window_minutes": 10080}}
            return {"timestamp": stamp, "payload": {"rate_limits": limits}}

        parent = self.home / "sessions/rollout-parent.jsonl"
        rows = [quota_row("2033-05-18T09:00:00Z", 56), quota_row("2033-05-18T10:00:00Z", 2)]
        write_lines(parent, rows)
        os.utime(parent, (NOW - 600, NOW - 600))
        # The subagent starts by copying that history, every row with the same new time.
        copied = "2033-05-18T11:00:00.123Z"
        child = self.home / "sessions/rollout-child.jsonl"
        write_lines(child, [quota_row(copied, 56), quota_row(copied, 2), {"type": "x"}])
        os.utime(child, (NOW, NOW))
        reading = codex_quota(self.home)
        self.assertEqual(reading["observedAt"], "2033-05-18T10:00:00Z")
        self.assertEqual(reading["windows"][0]["usedPercent"], 2.0)

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
        stale = {
            **base,
            "observedAt": NOW - 7 * 3600,
            "windows": [{**week, "usedPercent": 10}],
        }
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


class MainTests(unittest.TestCase):
    """Run the CLI in-process so argument handling is covered too."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        write_lines(self.home / "sessions/rollout-x.jsonl", codex_rows())

    def run_main(self, *argv):
        out = io.StringIO()
        args = patch.object(sys, "argv", ["usage_report.py", *argv])
        clock = patch.object(usage_report.time, "time", lambda: NOW)
        with args, clock, contextlib.redirect_stdout(out):
            usage_report.main()
        return out.getvalue()

    def homes(self):
        return ["--codex-home", str(self.home), "--claude-home", str(self.home / "none")]

    def test_tokens_json_defaults_until_to_now(self):
        report = json.loads(
            self.run_main("tokens", "--since", "2033-05-18T00:00:00Z", *self.homes())
        )
        self.assertEqual(report["until"], "2033-05-18T12:00:00Z")
        self.assertEqual(report["providers"][0]["totalTokens"], 140)
        self.assertEqual(report["providers"][1]["byModel"], [])

    def test_quota_from_codex_logs_and_from_a_file(self):
        logs = json.loads(self.run_main("quota", *self.homes()))
        self.assertEqual(logs["source"], "codex_session_log")
        status = self.home / "status.json"
        status.write_text(json.dumps({"rate_limits": {"seven_day": {"used_percentage": 10}}}))
        saved = json.loads(
            self.run_main(
                "quota",
                "--file",
                str(status),
                "--observed-at",
                "2033-05-18T11:00:00Z",
                *self.homes(),
            )
        )
        self.assertEqual(saved["source"], "claude_status_line")
        self.assertEqual(saved["weeklyUsedPercent"], 10)
        missing = json.loads(self.run_main("quota", "--codex-home", str(self.home / "none")))
        self.assertEqual(missing, {"suggestion": "unknown", "reasons": ["no_quota_reading"]})

    def test_invalid_or_missing_times_are_rejected(self):
        bare = self.home / "bare.json"
        bare.write_text(json.dumps({"rate_limits": {"seven_day": {"used_percentage": 10}}}))
        for argv in (
            ("tokens", "--since", "yesterday"),
            ("tokens", "--since", "2033-05-18T10:00:00Z", "--until", "2033-05-18T09:00:00Z"),
            ("quota", "--file", str(bare)),
            ("quota", "--file", str(bare), "--observed-at", "noon"),
        ):
            quiet = contextlib.redirect_stderr(io.StringIO())
            with self.subTest(argv=argv), self.assertRaises(SystemExit), quiet:
                self.run_main(*argv)


if __name__ == "__main__":
    unittest.main()

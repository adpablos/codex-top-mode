import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run
import usage_report
from capacity_policy import fingerprint
from usage_monitor import snapshot
from usage_report import iso

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/profile.example.json"
NOW = 2000000000.0  # 2033-05-18T03:33:20Z
HOUR = 3600


def profile(**limits):
    p = json.loads(EXAMPLE.read_text())
    p["authorization"].update(approvedAt=iso(NOW - HOUR), validUntil=None)
    p["limits"].update(limits)
    return p


def log_reading(used=40, at=NOW, renews=NOW + 30 * HOUR):
    window = {"usedPercent": used, "windowDurationMins": 10080, "resetsAt": renews}
    payload = {"rateLimitsByLimitId": {"codex": {"primary": window}}}
    return {"source": "codex_session_log", **snapshot(payload, iso(at))}


def fresh(p=None, hours=2, agents=("codex",), found=None):
    data = {"schemaVersion": 1, "runs": []}
    found = found if found is not None else {"codex": log_reading(), "claude": None}
    return data, run.start(data, p or profile(), hours, list(agents), found, NOW)


def new_task(r, task_id="fix-import", status="planned", at=NOW, **fields):
    defaults = {
        "project": "notes-app",
        "objective": "Stop duplicate imports",
        "doneWhen": "Two imports leave one entry, with a test",
        "owner": "anyone",
    }
    return run.record_task(r, task_id, {**defaults, **fields, "status": status}, at)


def setUpModule():
    # A CodexBar installed on the test machine must not change the results.
    patcher = patch.object(usage_report, "CODEXBAR", "codexbar-not-installed")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class StartTests(unittest.TestCase):
    def test_the_deadline_is_the_requested_time_when_nothing_caps_it(self):
        data, r = fresh()
        self.assertEqual(r["deadline"], iso(NOW + 2 * HOUR))
        self.assertIsNone(r["cappedBy"])
        self.assertEqual(r["fingerprint"], fingerprint(profile()))
        self.assertEqual(r["projects"], {"notes-app": "Notes app", "website": "Personal website"})
        self.assertIs(run.current(data), r)

    def test_the_deadline_is_capped_by_limits_approval_and_renewal(self):
        expiring = profile()
        expiring["authorization"]["validUntil"] = iso(NOW + HOUR)
        cases = [
            (profile(maximumHours=1), {}, "maximumHours", NOW + HOUR),
            (expiring, {}, "validUntil", NOW + HOUR),
            (
                profile(),
                {"codex": log_reading(renews=NOW + 600)},
                "codex weekly renewal",
                NOW + 600,
            ),
        ]
        for p, found, capped, deadline in cases:
            with self.subTest(capped):
                found = {"codex": log_reading(), "claude": None, **found}
                _, r = fresh(p, hours=3, found=found)
                self.assertEqual((r["cappedBy"], r["deadline"]), (capped, iso(deadline)))

    def test_a_renewal_counts_only_for_agents_the_run_uses_and_when_asked(self):
        found = {"codex": log_reading(renews=NOW + 600), "claude": None}
        _, r = fresh(found=found, agents=("claude",))
        self.assertIsNone(r["cappedBy"])
        self.assertEqual(
            r["unknown"], ["claude: renewal time unknown, so the run could not stop at it"]
        )
        _, r = fresh(profile(stopOnScheduledWeeklyRenewal=False), found=found)
        self.assertEqual((r["cappedBy"], r["unknown"]), (None, []))
        # A renewal time already past says nothing about the next one.
        _, r = fresh(found={"codex": log_reading(renews=NOW - 60), "claude": None})
        self.assertEqual(r["deadline"], iso(NOW + 2 * HOUR))
        self.assertEqual(len(r["unknown"]), 1)

    def test_refuses_a_second_run_a_dead_approval_or_no_time(self):
        data, _ = fresh()
        with self.assertRaisesRegex(ValueError, "still open"):
            run.start(data, profile(), 1, ["codex"], {"codex": None, "claude": None}, NOW)
        with self.assertRaisesRegex(ValueError, "used up"):
            fresh(found={"codex": log_reading(used=100), "claude": None})
        # Once its renewal time has passed, the reading no longer says it is used up.
        fresh(found={"codex": log_reading(used=100, renews=NOW - 60), "claude": None})
        expired = profile()
        expired["authorization"]["validUntil"] = iso(NOW - 1)
        for p, hours in ((expired, 1), (profile(), 0), (profile(), float("nan"))):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                fresh(p, hours=hours)


class TaskAndSessionTests(unittest.TestCase):
    def setUp(self):
        _, self.run = fresh()

    def test_a_task_needs_its_goal_and_owner_and_a_registered_project(self):
        with self.assertRaisesRegex(ValueError, "needs --project"):
            run.record_task(self.run, "t", {"status": "planned", "project": "notes-app"}, NOW)
        with self.assertRaisesRegex(ValueError, "Unknown project"):
            new_task(self.run, project="client-work")
        self.assertEqual(self.run["tasks"], [])

    def test_done_needs_evidence_and_blocked_needs_a_blocker(self):
        new_task(self.run)
        with self.assertRaisesRegex(ValueError, "evidence"):
            new_task(self.run, status="done")
        with self.assertRaisesRegex(ValueError, "blocker"):
            new_task(self.run, status="blocked")
        task = new_task(self.run, status="done", evidence="tests pass", at=NOW + 60)
        self.assertEqual(task["status"], "done")

    def test_a_task_can_wait_on_the_user_only_while_blocked(self):
        with self.assertRaisesRegex(ValueError, "goes with blocked"):
            new_task(self.run, status="in_progress", needsYou=True)
        merge = "Merge #186? It deploys to production; recommended"
        task = new_task(self.run, status="blocked", blocker=merge, needsYou=True)
        self.assertTrue(task["needsYou"])
        # A new blocker that does not wait on the user clears the flag, in the journal too.
        new_task(self.run, status="blocked", blocker="CI is running", at=NOW + 30)
        self.assertNotIn("needsYou", self.run["tasks"][0])
        new_task(self.run, status="blocked", blocker=merge, needsYou=True, at=NOW + 40)
        new_task(self.run, status="done", evidence="merged", at=NOW + 60)
        self.assertNotIn("needsYou", self.run["tasks"][0])

    def test_reaching_done_or_blocked_again_needs_fresh_words(self):
        new_task(self.run, status="done", evidence="old check")
        new_task(self.run, status="in_progress", at=NOW + 60)
        self.assertNotIn("evidence", self.run["tasks"][0])
        with self.assertRaisesRegex(ValueError, "evidence"):
            new_task(self.run, status="done", at=NOW + 120)
        new_task(self.run, status="blocked", blocker="Needs your login", at=NOW + 120)
        new_task(self.run, status="in_progress", at=NOW + 180)
        self.assertNotIn("blocker", self.run["tasks"][0])
        with self.assertRaisesRegex(ValueError, "blocker"):
            new_task(self.run, status="blocked", at=NOW + 240)

    def test_progress_is_recorded_once_per_change(self):
        new_task(self.run)
        new_task(self.run, status="in_progress", at=NOW + 60)
        task = new_task(self.run, status="in_progress", at=NOW + 120)
        self.assertEqual(
            task["events"],
            [{"at": iso(NOW), "status": "planned"}, {"at": iso(NOW + 60), "status": "in_progress"}],
        )
        self.assertEqual(len(self.run["tasks"]), 1)

    def test_sessions_are_recorded_once_and_end_once(self):
        run.record_session(self.run, "s1", "codex", "worker", False, NOW)
        run.record_session(self.run, "s1", "codex", "worker", True, NOW + 60)
        session = run.record_session(self.run, "s1", "codex", "worker", True, NOW + 120)
        self.assertEqual(session["endedAt"], iso(NOW + 60))
        self.assertEqual(len(self.run["sessions"]), 1)

    def test_a_session_must_spend_an_agent_named_at_start(self):
        with self.assertRaisesRegex(ValueError, "does not track claude"):
            run.record_session(self.run, "s1", "claude", "worker", False, NOW)
        self.assertEqual(self.run["sessions"], [])


class StatusTests(unittest.TestCase):
    def test_reports_time_left_tasks_threads_and_quota_age(self):
        _, r = fresh(profile(maximumActiveThreads=3))
        new_task(r, status="in_progress")
        run.record_session(r, "c", "codex", "coordinator", False, NOW)
        run.record_session(r, "w", "codex", "worker", False, NOW)
        found = {"codex": log_reading(at=NOW + 30 * 60), "claude": None}
        result = run.status(r, profile(maximumActiveThreads=3), found, NOW + HOUR)
        self.assertEqual(result["minutesLeft"], 60)
        self.assertFalse(result["stopNow"])
        self.assertEqual(
            result["tasks"]["in_progress"],
            [{"id": "fix-import", "project": "notes-app", "objective": "Stop duplicate imports",
              "owner": "anyone"}],
        )  # fmt: skip
        # Three threads: this coordinator, one worker, one free.
        self.assertEqual((result["activeSessions"], result["freeThreads"]), (1, 1))
        self.assertEqual(result["quota"]["codex"]["minutesOld"], 30)
        self.assertNotIn("claude", result["quota"])
        self.assertEqual(result["waitingOnYou"], [])

    def test_every_task_in_progress_takes_a_thread_and_owners_hide_session_ids(self):
        _, r = fresh(profile(maximumActiveThreads=3))
        run.record_session(r, "private-id", "codex", "worker", False, NOW)
        new_task(r, status="in_progress", owner="private-id")
        new_task(r, "docs", status="in_progress", owner="private-id")
        result = run.status(r, profile(maximumActiveThreads=3), {}, NOW)
        self.assertEqual(result["freeThreads"], 0)
        owners = [t["owner"] for t in result["tasks"]["in_progress"]]
        self.assertEqual(owners, ["codex worker session"] * 2)
        self.assertNotIn("private-id", json.dumps(result["tasks"]))

    def test_says_stop_at_the_deadline_or_when_the_setup_changes(self):
        p = profile()
        _, r = fresh(p)
        reasons = run.status(r, p, {}, NOW + 2 * HOUR)["stopReasons"]
        self.assertEqual(reasons, ["deadline"])
        changed = copy.deepcopy(p)
        changed["level"] = "autonomous"
        for current in (changed, None):
            with self.subTest(current=bool(current)):
                self.assertEqual(
                    run.status(r, current, {}, NOW)["stopReasons"], ["profile_changed"]
                )

    def test_says_stop_when_the_approval_ends(self):
        p = profile()
        p["authorization"]["validUntil"] = iso(NOW + HOUR)
        _, r = fresh(p)
        reasons = run.status(r, p, {}, NOW + HOUR)["stopReasons"]
        self.assertEqual(reasons, ["deadline", "authorization_ended"])


class StopAndReportTests(unittest.TestCase):
    def test_deadline_is_refused_as_a_reason_before_it_arrives(self):
        _, r = fresh()
        with self.assertRaisesRegex(ValueError, "real reason"):
            run.stop(r, "deadline", NOW + HOUR)
        run.stop(r, "deadline", NOW + 2 * HOUR - 30)
        self.assertEqual(r["stopReason"], "deadline")

    def test_stop_ends_assignments_and_close_ends_the_run(self):
        p = profile()
        _, r = fresh(p)
        new_task(r, status="in_progress")
        new_task(r, "docs")
        run.record_session(r, "w", "codex", "worker", False, NOW)
        with self.assertRaisesRegex(ValueError, "Stop the run first"):
            run.close(r, {}, NOW)
        run.stop(r, "user", NOW + 60)
        with self.assertRaisesRegex(ValueError, "already stopped"):
            run.stop(r, "user", NOW + 90)
        result = run.status(r, p, {}, NOW + 90)
        self.assertEqual((result["stopNow"], result["stoppedAt"]), (True, iso(NOW + 60)))
        # After the stop only checkpoints go in: no new work.
        for refused in (
            lambda: new_task(r, "new"),
            lambda: new_task(r, "docs", status="in_progress"),
            lambda: run.record_task(r, "docs", {"status": "planned", "owner": "you"}, NOW + 90),
            lambda: run.record_session(r, "w2", "codex", "worker", False, NOW + 90),
        ):
            with self.assertRaisesRegex(ValueError, "The run stopped"):
                refused()
        self.assertEqual((len(r["tasks"]), r["tasks"][1]["status"]), (2, "planned"))
        new_task(r, status="blocked", blocker="Waiting on CI", at=NOW + 120)
        run.record_session(r, "w", "codex", "worker", True, NOW + 120)
        run.close(r, {"codex": log_reading(at=NOW + 180)}, NOW + 180)
        self.assertEqual((r["stoppedAt"], r["endedAt"]), (iso(NOW + 60), iso(NOW + 180)))
        self.assertIsNone(run.current({"runs": [r]}))

    def test_the_report_keeps_the_facts_and_leaves_the_story_to_the_agent(self):
        found = {"codex": log_reading(used=38), "claude": None}
        _, r = fresh(found=found, agents=("codex", "claude"))
        new_task(r, status="done", evidence="2 new tests pass; merged")
        new_task(r, "alerts", project="website", status="blocked", blocker="Needs your login")
        new_task(r, "merge", status="blocked", blocker="Merge #12? Recommended: yes", needsYou=True)
        new_task(r, "ask", status="blocked", blocker="Grant access?", needsYou=True)
        new_task(r, "docs", status="in_progress", owner="you")
        new_task(r, "lint", status="in_progress", owner="w1")
        run.record_session(r, "w1", "codex", "worker", True, NOW)
        run.stop(r, "user", NOW)
        after = {"codex": log_reading(used=71, at=NOW + HOUR), "claude": None}
        run.close(r, after, NOW + 10 * 60)
        text = run.report(r, "TOKENS TABLE")
        for expected in (
            "- Done: Stop duplicate imports. Verified: 2 new tests pass; merged.",
            "**Personal website**\n- Blocked: Stop duplicate imports. Needs your login.",
            "- Not finished (in progress): Stop duplicate imports. Next: you.",
            "- Not finished (in progress): Stop duplicate imports. Next: codex worker session.",
            "| Stopped | 2033-05-18 03:33 UTC: you asked to stop |",
            "| Closed | 2033-05-18 03:43 UTC, after collecting checkpoints |",
            "## Waiting on you\n\n- **Notes app:** Stop duplicate imports. Merge #12? "
            "Recommended: yes.",
            "- **Notes app:** Stop duplicate imports. Grant access?\n\n## What changed",
            "- Blocked: Stop duplicate imports. Merge #12? Recommended: yes. Next: you.",
            "| Weekly quota, codex | 38% used at 2033-05-18 03:33 UTC → 71% used at "
            "2033-05-18 04:33 UTC (Codex local logs). Includes anything else",
            "| Weekly quota, claude | unknown: no reading; install CodexBar to see it",
            "| Sessions | codex worker: 1 started, 1 finished (plus this coordinator) |",
            "TOKENS TABLE",
            "- claude: renewal time unknown",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("w1", text)

    def test_a_renewal_between_readings_is_not_counted_as_the_runs_use(self):
        _, r = fresh()
        after = log_reading(used=3, at=NOW + HOUR, renews=NOW + 200 * HOUR)
        run.stop(r, "weekly_renewal", NOW + HOUR)
        run.close(r, {"codex": after}, NOW + HOUR)
        text = run.report(r, "")
        self.assertIn("renewed in between, so the difference is not this run's use", text)
        self.assertIn("No tasks were recorded.", text)
        self.assertNotIn("plus this coordinator", run.report(self.with_coordinator(r), ""))

    @staticmethod
    def with_coordinator(r):
        r = copy.deepcopy(r)
        coordinator = {"agent": "codex", "role": "coordinator", "endedAt": iso(NOW)}
        r["sessions"].append({"id": "c", "startedAt": iso(NOW), **coordinator})
        return r


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.private = root / "private"
        self.private.mkdir(mode=0o700)
        self.codex = root / "codex"
        self.profile = self.private / "profile.json"
        self.profile.write_text(json.dumps(profile()))
        self.profile.chmod(0o600)

    def cli(self, *argv, at=NOW):
        args = ["run.py", *argv, "--private", str(self.private)]
        if argv[0] in ("start", "status", "close"):
            args += ["--profile", str(self.profile), "--codex-home", str(self.codex)]
            args += ["--claude-home", str(self.codex)]
        out = io.StringIO()
        clock = patch.object(run.time, "time", return_value=at)
        with patch.object(sys, "argv", args), clock, contextlib.redirect_stdout(out):
            run.main()
        return json.loads(out.getvalue())

    def refused(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            self.cli(*argv)
        return err.getvalue()

    def test_a_whole_run_from_start_to_report(self):
        self.assertEqual(self.cli("status"), {"active": False, "lastRun": None})
        self.assertFalse((self.private / "runs.json").exists())
        started = self.cli("start", "--hours", "2", "--agents", "codex")
        self.assertEqual(started["deadline"], iso(NOW + 2 * HOUR))
        self.cli(
            "task", "fix", "--status", "done", "--project", "notes-app", "--objective", "Fix it",
            "--done-when", "tests pass", "--owner", "anyone", "--evidence", "tests pass",
        )  # fmt: skip
        session = self.cli("session", "private-id", "--agent", "codex", "--ended")
        self.assertNotIn("private-id", json.dumps(session))
        task = self.cli("task", "fix", "--status", "done", "--owner", "private-id")
        self.assertEqual(task["owner"], "codex worker session")
        self.cli(
            "task", "pr", "--status", "blocked", "--project", "notes-app", "--objective", "Ship",
            "--done-when", "merged", "--owner", "anyone", "--blocker", "Merge it?", "--needs-you",
        )  # fmt: skip
        self.assertEqual(self.cli("status")["waitingOnYou"][0]["id"], "pr")
        self.assertEqual(self.cli("status", at=NOW + 60)["tasks"]["done"][0]["id"], "fix")
        stopped = self.cli("stop", "--reason", "nothing_ready", at=NOW + HOUR)
        self.assertEqual(stopped["stoppedAt"], iso(NOW + HOUR))
        self.assertTrue(self.cli("status", at=NOW + HOUR)["stopNow"])
        closed = self.cli("close", at=NOW + HOUR + 60)
        report = Path(closed["report"])
        self.assertEqual(report.name, "2033-05-18-033320.md")
        self.assertIn("no ready work was left", report.read_text())
        last = self.cli("status")["lastRun"]
        self.assertEqual((last["endedAt"], last["report"]), (iso(NOW + HOUR + 60), str(report)))
        for path in (report, self.private / "runs.json"):
            self.assertFalse(path.stat().st_mode & 0o077)
        self.assertIn("private-id", (self.private / "runs.json").read_text())
        self.assertNotIn("private-id", report.read_text())

    def test_refuses_work_without_an_open_run(self):
        for argv in (
            ("task", "x", "--status", "planned"),
            ("stop", "--reason", "user"),
            ("close",),
        ):
            self.assertIn("No run is open", self.refused(*argv))

    def test_two_runs_started_in_the_same_second_keep_both_reports(self):
        for _ in range(2):
            self.cli("start", "--hours", "1", "--agents", "codex")
            self.cli("stop", "--reason", "user")
            self.cli("close")
        names = sorted(p.name for p in (self.private / "reports").iterdir())
        self.assertEqual(names, ["2033-05-18-033320-2.md", "2033-05-18-033320.md"])

    def test_a_broken_setup_shows_as_changed(self):
        self.cli("start", "--hours", "1", "--agents", "codex")
        self.profile.write_text("{}")
        self.assertEqual(self.cli("status")["stopReasons"], ["profile_changed"])

    def test_quota_comes_from_codexbar_when_it_answers(self):
        bar = {**log_reading(used=9), "source": "codexbar"}
        answers = {"claude": bar}
        with patch.object(usage_report, "codexbar_quota", lambda agent, run: answers.get(agent)):
            self.cli("start", "--hours", "1", "--agents", "codex", "claude")
        journal = json.loads((self.private / "runs.json").read_text())
        before = journal["runs"][0]["quotaBefore"]
        self.assertEqual(before["claude"]["source"], "codexbar")
        self.assertIsNone(before["codex"])  # no CodexBar answer and no Codex logs

    def test_private_files_stay_out_of_git(self):
        (self.private / ".git").mkdir()
        self.assertIn("outside Git", self.refused("start", "--hours", "1", "--agents", "codex"))

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_refuses_a_folder_others_can_read(self):
        self.private.chmod(0o755)
        self.assertIn("owner-only", self.refused("start", "--hours", "1", "--agents", "codex"))


if __name__ == "__main__":
    unittest.main()

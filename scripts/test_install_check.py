import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check
import install
from usage_monitor import epoch


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def test_links_into_each_installed_agent_and_skips_missing_ones(self):
        (self.home / ".codex").mkdir()
        results = install.install(self.home, {})
        link = self.home / ".codex/skills/top-mode"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), install.PACKAGE)
        self.assertTrue((link / "SKILL.md").is_file())
        self.assertEqual(results["Claude Code"], "skipped: agent not found")
        self.assertFalse((self.home / ".claude").exists())

    def test_is_idempotent_and_never_replaces_something_else(self):
        (self.home / ".codex").mkdir()
        other = self.home / ".claude/skills/top-mode"
        other.mkdir(parents=True)
        install.install(self.home, {})
        again = install.install(self.home, {})
        self.assertTrue(again["Codex"].startswith("already installed"))
        self.assertTrue(again["Claude Code"].startswith("not changed"))
        self.assertTrue(other.is_dir() and not other.is_symlink())

    def test_remove_only_deletes_our_links(self):
        (self.home / ".codex").mkdir()
        (self.home / ".claude/skills").mkdir(parents=True)
        (self.home / ".claude/skills/top-mode").symlink_to(self.home)
        install.install(self.home, {})
        results = install.remove(self.home, {})
        self.assertFalse((self.home / ".codex/skills/top-mode").exists())
        self.assertEqual(results["Claude Code"], "nothing to remove")
        self.assertTrue((self.home / ".claude/skills/top-mode").is_symlink())

    def test_follows_codex_home_and_claude_config_dir(self):
        env = {"CODEX_HOME": str(self.home / "codex"), "CLAUDE_CONFIG_DIR": ""}
        (self.home / "codex").mkdir()
        (self.home / ".codex").mkdir()
        install.install(self.home, env)
        self.assertTrue((self.home / "codex/skills/top-mode").is_symlink())
        self.assertFalse((self.home / ".codex/skills").exists())


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.now = epoch("2033-05-18T12:00:00Z")

    def status(self, used, hours, age=0):
        path = self.private / "claude-status.json"
        limits = {"seven_day": {"used_percentage": used, "resets_at": self.now + hours * 3600}}
        reading = {"observedAt": self.now - age * 3600, "payload": {"rate_limits": limits}}
        path.write_text(json.dumps(reading))

    def run_check(self, *argv):
        out = io.StringIO()
        args = ["check.py", "--codex-home", str(self.root / "none"), "--private"]
        args += [str(self.private), *argv]
        argv_patch = patch.object(sys, "argv", args)
        clock = patch.object(check.time, "time", lambda: self.now)
        with argv_patch, clock, contextlib.redirect_stdout(out):
            check.main()
        return out.getvalue()

    def test_quiet_when_there_is_nothing_to_do(self):
        self.status(used=90, hours=10)
        self.assertEqual(self.run_check(), "")
        self.assertIn("Claude: 90% of the weekly allowance used", self.run_check("--verbose"))

    def test_speaks_up_about_unused_quota_near_renewal(self):
        self.status(used=40, hours=10)
        self.assertEqual(
            self.run_check(),
            "Claude: 60% of the weekly allowance is unused and it renews in 10 h. "
            "Worth a Top Mode run.\n",
        )

    def test_scheduled_checks_tell_the_same_news_once_a_day(self):
        self.status(used=40, hours=30)
        self.assertNotEqual(self.run_check(), "")
        self.assertEqual(self.run_check(), "")
        self.assertIn("Worth a Top Mode run", self.run_check("--verbose"))
        self.now += 21 * 3600
        self.status(used=40, hours=9)
        self.assertIn("renews in 9 h", self.run_check())
        state = self.private / "check-state.json"
        if os.name == "posix":
            self.assertEqual(state.stat().st_mode & 0o077, 0)

    def test_a_saved_reading_needs_its_own_capture_time(self):
        path = self.private / "claude-status.json"
        limits = {"seven_day": {"used_percentage": 40, "resets_at": self.now + 3600}}
        path.write_text(json.dumps({"rate_limits": limits}))
        os.utime(path, (self.now, self.now))
        self.assertEqual(self.run_check(), "")
        self.assertIn("Claude: no quota reading (", self.run_check("--verbose"))

    def test_a_stale_reading_asks_for_a_fresh_one_instead_of_a_run(self):
        self.status(used=40, hours=10, age=7)
        self.assertEqual(self.run_check(), "")
        output = self.run_check("--verbose")
        self.assertIn("Suggestion: refresh_or_wait.", output)
        self.assertNotIn("Worth a Top Mode run", output)

    def test_no_reading_is_quiet_unless_verbose(self):
        self.assertEqual(self.run_check(), "")
        self.assertEqual(
            self.run_check("--verbose"),
            "Codex: no quota reading (it appears once a Codex session reports its limits).\n"
            "Claude: no quota reading (save its status line as "
            "references/profile-contract.md shows).\n"
            "Announcements: watch not set up (optional).\n",
        )

    def test_never_writes_its_state_inside_a_git_worktree(self):
        self.status(used=40, hours=10)
        (self.private / "watch.json").write_text("{}")
        (self.root / ".git").mkdir()
        for argv in ((), ("--verbose",), ("--json",)):
            err = io.StringIO()
            with self.subTest(argv=argv), patch.object(check.subprocess, "run") as run:
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
                    self.run_check(*argv)
                self.assertIn("outside Git worktrees", err.getvalue())
                run.assert_not_called()  # the watch would write its lock and state there
        written = {p.name for p in self.private.iterdir()}
        self.assertEqual(written, {"claude-status.json", "watch.json"})

    def test_a_reading_without_a_weekly_window_is_not_a_missing_reading(self):
        path = self.private / "claude-status.json"
        limits = {"five_hour": {"used_percentage": 10, "resets_at": self.now + 3600}}
        path.write_text(json.dumps({"observedAt": self.now, "payload": {"rate_limits": limits}}))
        output = self.run_check("--verbose")
        self.assertIn("Claude: weekly allowance unknown", output)
        self.assertIn("Suggestion: unknown.", output)

    def test_never_follows_a_link_for_its_state(self):
        self.status(used=40, hours=10)
        target = self.root / "elsewhere.json"
        (self.private / "check-state.json").symlink_to(target)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_check()
        self.assertFalse(target.exists())

    def test_reports_new_announcements_from_the_watch(self):
        (self.private / "watch.json").write_text("{}")
        signal = {
            "kind": "needs_interpretation",
            "sourceUrl": "https://x.com/example_pub/status/1",
            "text": "Reset coming   tomorrow",
        }
        done = type("Done", (), {"returncode": 0, "stdout": json.dumps({"signals": [signal]})})
        with patch.object(check.subprocess, "run", return_value=done):
            output = self.run_check("--json")
        messages = json.loads(output)["messages"]
        url = "https://x.com/example_pub/status/1"
        self.assertEqual(messages, [f"New announcement to read: {url} (Reset coming tomorrow)"])


if __name__ == "__main__":
    unittest.main()

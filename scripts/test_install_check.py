import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check
import install
import usage_report
from usage_monitor import epoch


def setUpModule():
    # A CodexBar installed on the test machine must not change the results.
    patcher = patch.object(usage_report, "CODEXBAR", "codexbar-not-installed")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def test_links_into_each_installed_agent_and_skips_missing_ones(self):
        (self.home / ".codex").mkdir()
        results = install.install(self.home, {})
        link = self.home / ".codex/skills/quota-coach"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), install.PACKAGE)
        self.assertTrue((link / "SKILL.md").is_file())
        self.assertEqual(results["Claude Code"], "skipped: agent not found")
        self.assertFalse((self.home / ".claude").exists())

    def test_is_idempotent_and_never_replaces_something_else(self):
        (self.home / ".codex").mkdir()
        other = self.home / ".claude/skills/quota-coach"
        other.mkdir(parents=True)
        install.install(self.home, {})
        again = install.install(self.home, {})
        self.assertTrue(again["Codex"].startswith("already installed"))
        self.assertTrue(again["Claude Code"].startswith("not changed"))
        self.assertTrue(other.is_dir() and not other.is_symlink())

    def test_remove_only_deletes_our_links(self):
        (self.home / ".codex").mkdir()
        (self.home / ".claude/skills").mkdir(parents=True)
        (self.home / ".claude/skills/quota-coach").symlink_to(self.home)
        install.install(self.home, {})
        results = install.remove(self.home, {})
        self.assertFalse((self.home / ".codex/skills/quota-coach").exists())
        self.assertEqual(results["Claude Code"], "nothing to remove")
        self.assertTrue((self.home / ".claude/skills/quota-coach").is_symlink())

    def test_replaces_only_our_links_under_the_former_name(self):
        (self.home / ".codex/skills").mkdir(parents=True)
        (self.home / ".claude/skills").mkdir(parents=True)
        (self.home / ".codex/skills/top-mode").symlink_to(install.PACKAGE)
        (self.home / ".claude/skills/top-mode").symlink_to(self.home)
        results = install.install(self.home, {})
        self.assertIn("removed the old link", results["Codex"])
        self.assertFalse((self.home / ".codex/skills/top-mode").is_symlink())
        self.assertTrue((self.home / ".claude/skills/top-mode").is_symlink())
        (self.home / ".codex/skills/top-mode").symlink_to(install.PACKAGE)
        install.remove(self.home, {})
        self.assertEqual(list((self.home / ".codex/skills").iterdir()), [])

    def test_a_failed_link_makes_the_install_fail(self):
        (self.home / ".codex").mkdir()
        denied = patch.object(Path, "symlink_to", side_effect=OSError(13, "Permission denied"))
        argv = patch.object(sys, "argv", ["install.py", "--home", str(self.home)])
        out = io.StringIO()
        with argv, denied, contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            install.main()
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("Codex: failed: Permission denied", out.getvalue())

    def test_installs_for_one_agent_and_replaces_broken_links(self):
        (self.home / ".codex/skills").mkdir(parents=True)
        (self.home / ".claude/skills").mkdir(parents=True)
        (self.home / ".claude/skills/quota-coach").symlink_to(self.home / ".quota-coach")
        (self.home / ".claude/skills/top-mode").symlink_to(self.home / ".top-mode")
        argv = ["install.py", "--home", str(self.home), "--agent", "claude"]
        out = io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
            install.main()
        self.assertNotIn("Codex", out.getvalue())
        self.assertIn("replaced a broken link; removed the old link", out.getvalue())
        self.assertEqual((self.home / ".claude/skills/quota-coach").resolve(), install.PACKAGE)
        self.assertFalse((self.home / ".claude/skills/top-mode").is_symlink())
        self.assertEqual(list((self.home / ".codex/skills").iterdir()), [])
        (self.home / ".codex/skills/quota-coach").symlink_to(self.home / "top-mode")
        (self.home / ".codex/skills/top-mode").symlink_to(self.home / "my-own-skill")
        results = install.remove(self.home, {}, {"Codex"})
        self.assertEqual(list(results), ["Codex"])
        kept = list((self.home / ".codex/skills").iterdir())
        self.assertEqual(kept, [self.home / ".codex/skills/top-mode"])

    def test_follows_codex_home_and_claude_config_dir(self):
        env = {"CODEX_HOME": str(self.home / "codex"), "CLAUDE_CONFIG_DIR": ""}
        (self.home / "codex").mkdir()
        (self.home / ".codex").mkdir()
        install.install(self.home, env)
        self.assertTrue((self.home / "codex/skills/quota-coach").is_symlink())
        self.assertFalse((self.home / ".codex/skills").exists())


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.now = epoch("2033-05-18T12:00:00Z")
        self.claude = None

    def status(self, used, hours, age=0, minutes=10080):
        """A Claude reading, as CodexBar would give it."""
        window = {"slot": "secondary", "usedPercent": used, "durationMinutes": minutes}
        self.claude = {
            "source": "codexbar",
            "observedAt": self.now - age * 3600,
            "windows": [{**window, "resetsAt": self.now + hours * 3600}],
            "availableResets": None,
            "grantTimes": [],
            "resetExpirations": [],
        }

    def run_check(self, *argv):
        out = io.StringIO()
        args = ["check.py", "--codex-home", str(self.root / "none"), "--private"]
        args += [str(self.private), *argv]
        argv_patch = patch.object(sys, "argv", args)
        clock = patch.object(check.time, "time", lambda: self.now)
        reading = lambda agent, home: self.claude if agent == "claude" else None  # noqa: E731
        quota = patch.object(check, "latest_quota", reading)
        with argv_patch, clock, quota, contextlib.redirect_stdout(out):
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
        # Asking on demand always shows the full status.
        self.assertIn("Worth a Top Mode run", self.run_check("--verbose"))
        self.assertIn("Worth a Top Mode run", self.run_check("--json"))
        self.assertEqual(self.run_check(), "")
        self.now += 21 * 3600
        self.status(used=40, hours=9)
        self.assertIn("renews in 9 h", self.run_check())
        state = self.private / "check-state.json"
        if os.name == "posix":
            self.assertEqual(state.stat().st_mode & 0o077, 0)

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
            "Claude: no quota reading (install CodexBar "
            "(https://codexbar.app) to see it).\n",
        )

    def test_never_writes_its_state_inside_a_git_worktree(self):
        self.status(used=40, hours=10)
        (self.root / ".git").mkdir()
        for argv in ((), ("--verbose",), ("--json",)):
            err = io.StringIO()
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
                    self.run_check(*argv)
                self.assertIn("outside Git worktrees", err.getvalue())
        written = {p.name for p in self.private.iterdir()}
        self.assertEqual(written, set())

    def test_a_reading_without_a_weekly_window_is_not_a_missing_reading(self):
        self.status(used=10, hours=1, minutes=300)
        output = self.run_check("--verbose")
        self.assertIn("Claude: weekly allowance unknown", output)
        self.assertIn("Suggestion: unknown.", output)

    def test_never_follows_a_link_for_its_private_files(self):
        self.status(used=40, hours=10)
        for name in ("check-state.json",):
            with self.subTest(name=name):
                path = self.private / name
                saved = path.read_bytes() if path.is_file() else None
                path.unlink(missing_ok=True)
                target = self.root / "elsewhere.json"
                path.symlink_to(target)
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    self.run_check()
                self.assertFalse(target.exists())
                path.unlink()
                if saved is not None:
                    path.write_bytes(saved)


if __name__ == "__main__":
    unittest.main()

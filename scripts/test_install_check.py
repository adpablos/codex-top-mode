import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check
import install
import usage_report
from common import epoch


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

    def test_check_is_read_only_and_names_both_old_and_current_copies(self):
        (self.home / ".codex/skills").mkdir(parents=True)
        other = self.home / "other-copy"
        other.mkdir()
        (self.home / ".codex/skills/quota-coach").symlink_to(other)
        (self.home / ".codex/skills/top-mode").symlink_to(self.home / "missing")
        before = sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertFalse(install.check(self.home, {}))
        self.assertIn("different copy", out.getvalue())
        self.assertIn(str(other), out.getvalue())
        self.assertIn("former skill present", out.getvalue())
        self.assertEqual(
            before, sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))
        )
        self.assertEqual(install.revision(other), "unknown (no Git checkout)")

    def test_check_reports_broken_links_and_conflicts_without_replacing_them(self):
        link = self.home / ".codex/skills/quota-coach"
        link.parent.mkdir(parents=True)
        for kind in ("missing", "broken", "file", "directory"):
            with self.subTest(kind=kind), contextlib.redirect_stdout(io.StringIO()):
                if kind == "broken":
                    link.symlink_to(self.home / "missing")
                elif kind == "file":
                    link.write_text("another skill")
                elif kind == "directory":
                    link.mkdir()
                self.assertFalse(install.check(self.home, {}))
                if link.is_dir():
                    link.rmdir()
                elif link.exists() or link.is_symlink():
                    link.unlink()

    def test_install_cli_fails_for_an_occupied_or_missing_selected_agent(self):
        for present in (False, True):
            if present:
                (self.home / ".codex/skills/quota-coach").mkdir(parents=True)
            argv = ["install.py", "--home", str(self.home), "--agent", "codex"]
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(SystemExit) as stop,
            ):
                install.main()
            self.assertEqual(stop.exception.code, 1)

    def test_check_cli_succeeds_only_for_a_ready_selected_agent(self):
        (self.home / ".codex").mkdir()
        install.install(self.home, {})
        argv = ["install.py", "--home", str(self.home), "--check", "--agent", "codex"]
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as stop,
        ):
            install.main()
        self.assertEqual(stop.exception.code, 0)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.repo = root / "installed"
        self.remote = root / "upstream"
        # Keep user signing, hooks and global excludes out of these synthetic repositories.
        self.env = patch.dict(
            os.environ,
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.remote.mkdir()
        self.repo.mkdir()
        install.git(self.remote, "init", "-b", "main")
        (self.remote / "SKILL.md").write_text("fixture v1")
        install.git(self.remote, "add", "SKILL.md")
        install.git(self.remote, "commit", "-m", "First version")
        install.git(self.repo, "clone", str(self.remote), ".")
        install.git(
            self.repo, "remote", "set-url", "origin", "https://github.com/adpablos/quota-coach.git"
        )
        self.before = install.git(self.repo, "rev-parse", "HEAD")
        (self.remote / "SKILL.md").write_text("fixture v2")
        install.git(self.remote, "commit", "-am", "Second version")
        self.after = install.git(self.remote, "rev-parse", "HEAD")
        package = patch.object(install, "PACKAGE", self.repo)
        package.start()
        self.addCleanup(package.stop)
        self.real_git = install.git

    def update(self):
        def local_fetch(folder, *args):
            if args == ("fetch", "origin", "refs/heads/main"):
                return self.real_git(folder, "fetch", str(self.remote), "refs/heads/main")
            return self.real_git(folder, *args)

        with patch.object(install, "git", side_effect=local_fetch):
            install.update()

    def test_fast_forward_keeps_links_and_private_state_and_is_repeatable(self):
        home = self.repo.parent / "home"
        (home / ".codex").mkdir(parents=True)
        private = home / "private.json"
        private.write_text("private fixture stays unchanged")
        install.install(home, {})
        self.update()
        self.update()
        self.assertEqual(install.git(self.repo, "rev-parse", "HEAD"), self.after)
        self.assertEqual((home / ".codex/skills/quota-coach/SKILL.md").read_text(), "fixture v2")
        self.assertEqual(private.read_text(), "private fixture stays unchanged")
        self.assertIn(self.after, install.revision(self.repo))
        install.git(self.repo, "tag", "v0.1.0-test")
        self.assertIn("v0.1.0-test", install.revision(self.repo))

    def test_refuses_dirty_development_and_unrecognized_checkouts(self):
        (self.repo / "local.txt").write_text("keep me")
        with self.assertRaisesRegex(ValueError, "Local changes"):
            self.update()
        self.assertIn("local changes", install.revision(self.repo))
        (self.repo / "local.txt").unlink()
        install.git(self.repo, "switch", "-c", "work")
        with self.assertRaisesRegex(ValueError, "requires main"):
            self.update()
        install.git(self.repo, "switch", "main")
        install.git(self.repo, "remote", "set-url", "origin", "https://example.invalid/quota-coach")
        with self.assertRaisesRegex(ValueError, "not the Quota Coach"):
            self.update()
        self.assertEqual(install.git(self.repo, "rev-parse", "HEAD"), self.before)

    def test_refuses_local_commits_including_an_ahead_main(self):
        self.update()
        (self.repo / "local.txt").write_text("preserve local commit")
        install.git(self.repo, "add", "local.txt")
        install.git(self.repo, "commit", "-m", "Local commit")
        head = install.git(self.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "Local commits"):
            self.update()
        self.assertEqual(install.git(self.repo, "rev-parse", "HEAD"), head)

    def test_archive_and_git_failure_are_explicit(self):
        shutil.rmtree(self.repo / ".git")
        with self.assertRaisesRegex(ValueError, "Git checkout"):
            self.update()
        (self.repo / ".git").mkdir()
        with patch.object(install, "git", side_effect=FileNotFoundError):
            self.assertIn("Git unavailable", install.revision(self.repo))

    def test_update_cli_restarts_the_updated_installer_and_preserves_agent_selection(self):
        argv = ["install.py", "--update", "--agent", "claude"]
        with (
            patch.object(sys, "argv", argv),
            patch.object(install, "update") as update,
            patch.object(install.subprocess, "call", return_value=1) as call,
            self.assertRaises(SystemExit) as stop,
        ):
            install.main()
        update.assert_called_once()
        self.assertEqual(stop.exception.code, 1)
        self.assertEqual(call.call_args.args[0][-2:], ["--agent", "claude"])
        self.assertIn(str(self.repo / "scripts/install.py"), call.call_args.args[0])

    def test_git_error_does_not_disclose_remote_credentials(self):
        error = subprocess.CalledProcessError(1, ["git"], stderr="https://secret@example.invalid")
        with (
            patch.object(sys, "argv", ["install.py", "--update"]),
            patch.object(install, "update", side_effect=error),
            contextlib.redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit),
        ):
            install.main()
        self.assertIn("Git update failed", err.getvalue())
        self.assertNotIn("secret", err.getvalue())


class FirstRunTests(unittest.TestCase):
    def test_installed_skill_can_resume_stop_and_close_from_a_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            home, private, project = (root / name for name in ("home", "private", "project"))
            (home / ".codex").mkdir(parents=True)
            private.mkdir(mode=0o700)
            project.mkdir()
            # Only Git is on PATH: no installed CodexBar or account-backed CLI can run.
            commands = root / "bin"
            commands.mkdir()
            (commands / "git").symlink_to(shutil.which("git"))
            env = {
                **os.environ,
                "PATH": str(commands),
                "CODEX_HOME": str(home / ".codex"),
                "CLAUDE_CONFIG_DIR": str(home / "missing-claude"),
            }

            def cli(script, *args, success=True):
                result = subprocess.run(
                    [sys.executable, "-B", str(script), *map(str, args)],
                    cwd=project,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if success:
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                return result.stdout

            cli(install.PACKAGE / "scripts/install.py", "--home", home, "--agent", "codex")
            scripts = home / ".codex/skills/quota-coach/scripts"
            self.assertIn(
                "ready for a new session",
                cli(scripts / "install.py", "--check", "--agent", "codex"),
            )
            fixture = json.loads((install.PACKAGE / "examples/profile.example.json").read_text())
            fixture["authorization"] = {
                "source": "Synthetic offline test, not real user permission",
                "approvedAt": "2000-01-01T00:00:00Z",
                "validUntil": None,
            }
            fixture["projects"] = {
                "sample": {
                    "label": "Sample",
                    "path": str(project),
                    "work": ["TODO.md"],
                    "priority": 0,
                }
            }
            profile = private / "profile.json"
            profile.write_text(json.dumps(fixture))
            profile.chmod(0o600)
            binding = private / "binding.json"
            cli(scripts / "profile_binding.py", "--binding", binding, "bind", "--profile", profile)
            located = json.loads(
                cli(scripts / "profile_binding.py", "--binding", binding, "locate")
            )
            self.assertEqual(located["profilePath"], str(profile))

            def run_cli(command, *args, success=True):
                sources = []
                if command in ("start", "status", "close"):
                    sources = [
                        "--profile",
                        profile,
                        "--codex-home",
                        home / ".codex",
                        "--claude-home",
                        home / "missing-claude",
                    ]
                out = cli(
                    scripts / "run.py",
                    command,
                    *args,
                    "--private",
                    private,
                    *sources,
                    success=success,
                )
                return json.loads(out) if success else out

            started = run_cli("start", "--hours", "0.25", "--agents", "codex")
            self.assertTrue(started["unknown"])
            run_cli("session", "fixture-session", "--agent", "codex", "--role", "coordinator")
            run_cli(
                "task",
                "fix",
                "--status",
                "in_progress",
                "--project",
                "sample",
                "--objective",
                "Write a sample result",
                "--done-when",
                "File contains done",
                "--owner",
                "fixture-session",
            )
            self.assertEqual(run_cli("status")["deadline"], started["deadline"])
            run_cli("stop", "--reason", "user")
            self.assertTrue(run_cli("status")["stopNow"])
            run_cli("task", "extra", "--status", "planned", success=False)
            result = project / "result.txt"
            result.write_text("done")
            self.assertEqual(result.read_text(), "done")
            run_cli("task", "fix", "--status", "done", "--evidence", "Read result.txt: done")
            run_cli(
                "session", "fixture-session", "--agent", "codex", "--role", "coordinator", "--ended"
            )
            closed = run_cli("close")
            report = Path(closed["report"]).read_text()
            self.assertIn("Read result.txt: done", report)
            self.assertNotIn("fixture-session", report)
            self.assertFalse(run_cli("status")["active"])
            self.assertEqual(json.loads(profile.read_text()), fixture)
            cli(scripts / "install.py", "--remove", "--agent", "codex")
            self.assertFalse(scripts.exists())
            self.assertTrue(Path(closed["report"]).is_file())


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

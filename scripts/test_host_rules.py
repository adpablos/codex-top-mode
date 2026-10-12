import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import host_rules
from host_rules import expected, sync

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/profile.example.json"
PACKAGE = Path("/home/you/.quota-coach")
MERGE = "Bash(gh pr merge:*)"
PUSH = "Bash(git push -u origin quota-coach/*)"


def profile(level="balanced", **actions):
    p = json.loads(EXAMPLE.read_text())
    p.update(level=level, actions=actions)
    return p


def where(rules: dict, rule: str) -> list:
    return [name for name, entries in rules.items() if rule in entries]


class ExpectedRulesTests(unittest.TestCase):
    def test_each_level_puts_merge_and_push_where_it_says(self):
        for level, merge, push in (
            ("careful", "ask", "ask"),
            ("balanced", "ask", "allow"),
            ("autonomous", "allow", "allow"),
        ):
            rules = expected(profile(level), PACKAGE)
            with self.subTest(level):
                self.assertEqual(where(rules, MERGE), [merge])
                self.assertEqual(where(rules, PUSH), [push])
                self.assertEqual(where(rules, "Bash(git commit:*)"), ["allow"])
                self.assertEqual(where(rules, "Bash(npm install:*)"), ["ask"])
                self.assertEqual(where(rules, "Bash(git push --force:*)"), ["deny"])

    def test_the_users_exceptions_win_over_the_level(self):
        rules = expected(profile("autonomous", merge="deny", destruction="ask"), PACKAGE)
        self.assertEqual(where(rules, MERGE), ["deny"])
        self.assertEqual(where(rules, "Bash(git reset --hard:*)"), ["ask"])

    def test_the_default_branch_is_denied_even_when_destruction_is_allowed(self):
        rules = expected(profile("autonomous", destruction="allowed"), PACKAGE)
        self.assertEqual(where(rules, "Bash(git push * main)"), ["deny"])
        self.assertEqual(where(rules, "Bash(git push *:master*)"), ["deny"])

    def test_projects_exclusions_and_checks_become_rules(self):
        rules = expected(profile(), PACKAGE)
        self.assertIn("Read(//home/you/projects/notes-app/**)", rules["allow"])
        self.assertIn("Edit(//home/you/projects/website/**)", rules["allow"])
        self.assertIn("Bash(npm test:*)", rules["allow"])
        self.assertIn("Edit(//home/you/projects/client-work/**)", rules["deny"])
        self.assertIn("Read(//home/you/projects/client-work/**)", rules["deny"])

    def test_the_own_scripts_are_allowed_as_an_agent_may_write_them(self):
        with patch.object(host_rules.Path, "home", return_value=Path("/home/you")):
            rules = expected(profile("careful"), PACKAGE)
        for folder in ("/home/you/.quota-coach", "~/.quota-coach"):
            self.assertIn(f"Bash(python3 -B {folder}/scripts/run.py:*)", rules["allow"])
            self.assertIn(
                f"Bash(python3 -B {folder}/scripts/profile_binding.py locate:*)", rules["allow"]
            )
        self.assertFalse(any("install.py" in r or "host_rules" in r for r in rules["allow"]))

    def test_each_rule_sits_in_one_list(self):
        rules = expected(profile("autonomous", read="ask", checks="deny"), PACKAGE)
        seen = [r for entries in rules.values() for r in entries]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(where(rules, "Bash(npm test:*)"), ["deny"])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.folder, self.private = root / "personal", root / "private"
        self.folder.mkdir()
        self.settings = self.folder / ".claude" / "settings.local.json"

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self, p, write=True):
        return sync(p, self.folder, self.private, write, PACKAGE)

    def stored(self):
        return json.loads(self.settings.read_text())

    def test_showing_writes_nothing(self):
        result = self.sync(profile(), write=False)
        self.assertFalse(result["current"])
        self.assertFalse(result["written"])
        self.assertIn(PUSH, result["add"]["allow"])
        self.assertFalse(self.settings.exists())
        self.assertFalse(self.private.exists())

    def test_writing_keeps_the_users_own_settings_and_rules(self):
        self.settings.parent.mkdir()
        mine = {"model": "x", "permissions": {"allow": ["Bash(make:*)"], "ask": [MERGE]}}
        self.settings.write_text(json.dumps(mine))
        self.assertTrue(self.sync(profile("autonomous"))["written"])
        stored = self.stored()
        self.assertEqual(stored["model"], "x")
        self.assertIn("Bash(make:*)", stored["permissions"]["allow"])
        self.assertIn(MERGE, stored["permissions"]["allow"])
        # The user's own ask stays; in Claude Code it wins over the allow.
        self.assertEqual(stored["permissions"]["ask"][0], MERGE)
        self.assertTrue(self.sync(profile("autonomous"), write=False)["current"])

    def test_a_new_level_moves_only_the_rules_it_added(self):
        self.sync(profile("autonomous"))
        self.assertIn(MERGE, self.stored()["permissions"]["allow"])
        result = self.sync(profile("careful"))
        self.assertIn(MERGE, result["remove"]["allow"])
        stored = self.stored()["permissions"]
        self.assertNotIn(MERGE, stored["allow"])
        self.assertNotIn(PUSH, stored["allow"])
        self.assertIn(MERGE, stored["ask"])
        self.assertIn(PUSH, stored["ask"])
        record = json.loads((self.private / "host-rules.json").read_text())
        self.assertNotIn(MERGE, record["claude"][str(self.settings)]["allow"])
        self.assertIn(MERGE, record["claude"][str(self.settings)]["ask"])

    def test_a_rule_the_user_had_is_never_removed(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({"permissions": {"allow": [MERGE]}}))
        self.sync(profile("autonomous"))
        self.sync(profile("careful"))
        self.assertIn(MERGE, self.stored()["permissions"]["allow"])

    def test_the_record_is_private(self):
        self.sync(profile())
        self.assertEqual((self.private / "host-rules.json").stat().st_mode & 0o077, 0)

    def test_refuses_a_linked_settings_file_or_a_broken_one(self):
        self.settings.parent.mkdir()
        target = Path(self.tmp.name) / "elsewhere.json"
        target.write_text("{}")
        self.settings.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "is a link"):
            self.sync(profile())
        self.settings.unlink()
        self.settings.write_text(json.dumps({"permissions": {"allow": "Bash(make:*)"}}))
        with self.assertRaisesRegex(ValueError, "lists of rules"):
            self.sync(profile())

    def test_refuses_a_folder_whose_git_would_pick_the_rules_up(self):
        subprocess.run(["git", "init", "-q", str(self.folder)], check=True)
        with self.assertRaisesRegex(ValueError, "Have Git ignore"):
            self.sync(profile())
        (self.folder / ".gitignore").write_text(".claude/settings.local.json\n")
        self.assertTrue(self.sync(profile())["written"])


class CommandLineTests(unittest.TestCase):
    def test_shows_then_writes_with_the_saved_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, private = root / "personal", root / "private"
            folder.mkdir()
            path = root / "profile.json"
            path.write_text(json.dumps(profile()))
            base = ["host_rules.py", "--agent", "claude", "--profile", str(path)]
            base += ["--folder", str(folder), "--private", str(private)]
            for extra, written in (([], False), (["--write"], True), ([], False)):
                out = io.StringIO()
                with patch.object(sys, "argv", base + extra), contextlib.redirect_stdout(out):
                    host_rules.main()
                result = json.loads(out.getvalue())
                self.assertEqual(result["written"], written)
            self.assertTrue(result["current"])

    def test_a_relative_folder_is_refused(self):
        err = io.StringIO()
        argv = ["host_rules.py", "--agent", "claude", "--profile", str(EXAMPLE), "--folder", "x"]
        with (
            patch.object(sys, "argv", argv),
            contextlib.redirect_stderr(err),
            self.assertRaises(SystemExit),
        ):
            host_rules.main()
        self.assertIn("absolute folder", err.getvalue())


if __name__ == "__main__":
    unittest.main()

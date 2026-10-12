import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import host_rules
from host_rules import codex_rules, codex_text, expected, sync_claude, sync_codex

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
                self.assertEqual(where(rules, "Bash(git push * --force*)"), ["deny"])

    def test_the_users_exceptions_win_over_the_level(self):
        rules = expected(profile("autonomous", merge="deny", destruction="ask"), PACKAGE)
        self.assertEqual(where(rules, MERGE), ["deny"])
        self.assertEqual(where(rules, "Bash(git reset --hard:*)"), ["ask"])

    def test_the_default_branch_is_denied_even_when_destruction_is_allowed(self):
        rules = expected(profile("autonomous", destruction="allowed"), PACKAGE)
        self.assertEqual(where(rules, "Bash(git push * main)"), ["deny"])
        self.assertEqual(where(rules, "Bash(git push *:master*)"), ["deny"])
        # `quota-coach/x:refs/heads/main` also matches the allowed run-branch push.
        self.assertEqual(where(rules, "Bash(git push *refs/heads/main*)"), ["deny"])

    def test_rewriting_a_branch_or_deleting_keychain_items_is_destruction(self):
        rules = expected(profile(), PACKAGE)
        for rule in (
            "git switch -C*",
            "git switch * -C*",
            "git switch * --force*",
            "git checkout -B*",
            "git worktree add * -B*",
            "security delete-*",
            "security * delete-*",
        ):
            self.assertEqual(where(rules, f"Bash({rule})"), ["deny"])

    def test_commands_with_destructive_options_are_allowed_only_narrowly(self):
        rules = expected(profile("autonomous", access="allowed"), PACKAGE)
        self.assertNotIn("Bash(git switch:*)", rules["allow"])
        self.assertIn("Bash(git switch -c quota-coach/*)", rules["allow"])
        self.assertIn("Bash(git switch --create quota-coach/*)", rules["allow"])
        self.assertNotIn("Bash(security:*)", rules["allow"])
        self.assertIn("Bash(security find-*)", rules["allow"])

    def test_windows_folders_use_claude_codes_path_form(self):
        self.assertEqual(host_rules.folder_rule("Read", "C:\\work\\app"), "Read(//c/work/app/**)")
        self.assertEqual(host_rules.folder_rule("Edit", "/home/you/x"), "Edit(//home/you/x/**)")
        with self.assertRaisesRegex(ValueError, "Network folders"):
            host_rules.folder_rule("Read", "\\\\server\\share\\repo")

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
        root = Path(self.tmp.name).resolve()
        self.folder, self.private = root / "personal", root / "private"
        self.folder.mkdir()
        self.settings = self.folder / ".claude" / "settings.local.json"

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self, p, write=True):
        return sync_claude(p, self.folder, self.private, write, PACKAGE)

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
        (self.folder / ".gitignore").unlink()
        with self.assertRaisesRegex(ValueError, "Have Git ignore"):
            self.sync(profile())


def decision(rules: list, *pattern) -> list:
    return [d for p, d, _ in rules if p == list(pattern)]


class CodexRulesTests(unittest.TestCase):
    def test_each_level_puts_push_and_merge_where_it_says(self):
        for level, push, merge in (
            ("careful", "prompt", "prompt"),
            ("balanced", "allow", "prompt"),
            ("autonomous", "allow", "allow"),
        ):
            rules = codex_rules(profile(level), PACKAGE)
            with self.subTest(level):
                self.assertEqual(decision(rules, "git", "push", "origin"), [push])
                self.assertEqual(decision(rules, "git", "push", "-u", "origin"), [push])
                self.assertEqual(decision(rules, "git", "push"), [])
                self.assertEqual(decision(rules, "gh", "pr", "merge"), [merge])
                self.assertEqual(decision(rules, "git", "checkout", "-b"), ["allow"])
                self.assertEqual(decision(rules, "git", "switch", ["-c", "--create"]), ["allow"])
                self.assertEqual(decision(rules, "git", "switch"), [])
                self.assertEqual(decision(rules, "brew", "install"), ["prompt"])
                rewrite = ["--force", "--force-with-lease", "-f", "--delete", "-d"]
                self.assertEqual(decision(rules, "git", "push", rewrite), ["forbidden"])
                self.assertEqual(
                    decision(rules, "git", "push", "origin", ["main", "master"]), ["forbidden"]
                )

    def test_rewriting_a_branch_or_deleting_keychain_items_is_forbidden(self):
        rules = codex_rules(profile(), PACKAGE)
        self.assertEqual(decision(rules, "git", "checkout", ["--force", "-f", "-B"]), ["forbidden"])
        self.assertEqual(
            decision(rules, "git", "worktree", "add", ["--force", "-f", "-B"]), ["forbidden"]
        )
        forbidden = [p for p, d, _ in rules if d == "forbidden"]
        for command, option in (
            ("switch", "-C"),
            ("switch", "--discard-changes"),
            ("branch", "-D"),
        ):
            with self.subTest(option):
                matches = [p for p in forbidden if p[:2] == ["git", command] and option in p[2]]
                self.assertEqual(len(matches), 1)
        keychain = [p for p, d, _ in rules if p[0] == "security"]
        self.assertIn("find-certificate", keychain[0][1])
        self.assertTrue(all(w.startswith("delete-") for w in keychain[-1][1]))

    def test_the_users_exceptions_win_over_the_level(self):
        rules = codex_rules(profile("autonomous", merge="deny", destruction="ask"), PACKAGE)
        self.assertEqual(decision(rules, "gh", "pr", "merge"), ["forbidden"])
        self.assertEqual(decision(rules, "git", "reset", "--hard"), ["prompt"])

    def test_the_own_scripts_are_allowed_word_by_word(self):
        rules = codex_rules(profile("careful"), PACKAGE)
        script = "/home/you/.quota-coach/scripts/profile_binding.py"
        self.assertEqual(decision(rules, "python3", "-B", script, "locate"), ["allow"])
        self.assertFalse(any("install.py" in str(p) for p, _, _ in rules))

    def test_the_file_is_one_prefix_rule_per_line(self):
        rules = codex_rules(profile(), PACKAGE)
        read = []
        exec(  # The rules file is Starlark; this subset is also Python.
            codex_text(rules),
            {"prefix_rule": lambda **kw: read.append((kw["pattern"], kw["decision"]))},
        )
        self.assertEqual(read, [(p, d) for p, d, _ in rules])


class CodexSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name).resolve()
        self.path = self.folder / ".codex" / "rules" / "quota-coach.rules"

    def tearDown(self):
        self.tmp.cleanup()

    def test_shows_writes_and_rewrites_when_the_level_changes(self):
        result = sync_codex(profile(), self.folder, False, PACKAGE)
        self.assertFalse(result["current"])
        self.assertIn("git push origin", result["allow"])
        self.assertIn("gh pr merge", result["prompt"])
        self.assertFalse(self.path.exists())
        self.assertTrue(sync_codex(profile(), self.folder, True, PACKAGE)["written"])
        self.assertTrue(sync_codex(profile(), self.folder, False, PACKAGE)["current"])
        self.assertFalse(sync_codex(profile("careful"), self.folder, False, PACKAGE)["current"])
        sync_codex(profile("careful"), self.folder, True, PACKAGE)
        self.assertIn('["git", "push", "origin"], decision="prompt"', self.path.read_text())

    def test_refuses_a_linked_file_or_folder(self):
        self.path.parent.mkdir(parents=True)
        target = self.folder / "elsewhere.rules"
        target.write_text("")
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "is a link"):
            sync_codex(profile(), self.folder, True, PACKAGE)
        shutil.rmtree(self.folder / ".codex")
        (self.folder / "elsewhere").mkdir()
        (self.folder / ".codex").symlink_to(self.folder / "elsewhere")
        with self.assertRaisesRegex(ValueError, "is a link"):
            sync_codex(profile(), self.folder, False, PACKAGE)

    def test_follows_a_linked_start_folder_to_check_git(self):
        repo = self.folder / "repo"
        (repo / "sub").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        start = self.folder / "start"
        start.symlink_to(repo / "sub")
        with self.assertRaisesRegex(ValueError, "Have Git ignore"):
            sync_codex(profile(), start, True, PACKAGE)
        with self.assertRaisesRegex(ValueError, "Have Git ignore"):
            sync_claude(profile(), start, self.folder / "private", True, PACKAGE)
        self.assertEqual(list((repo / "sub").iterdir()), [])

    def test_refuses_a_file_git_would_pick_up_even_when_it_is_current(self):
        self.assertTrue(sync_codex(profile(), self.folder, True, PACKAGE)["written"])
        subprocess.run(["git", "init", "-q", str(self.folder)], check=True)
        self.assertTrue(sync_codex(profile(), self.folder, False, PACKAGE)["current"])
        with self.assertRaisesRegex(ValueError, "Have Git ignore"):
            sync_codex(profile(), self.folder, True, PACKAGE)
        (self.folder / ".git" / "info" / "exclude").write_text(".codex/\n")
        self.assertFalse(sync_codex(profile(), self.folder, True, PACKAGE)["written"])


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
            for agent in ("claude", "codex"):
                for extra, written in (([], False), (["--write"], True), ([], False)):
                    argv = [*base, *extra]
                    argv[2] = agent
                    out = io.StringIO()
                    with patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
                        host_rules.main()
                    result = json.loads(out.getvalue())
                    self.assertEqual((result["agent"], result["written"]), (agent, written))
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

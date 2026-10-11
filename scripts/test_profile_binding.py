import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from profile_binding import bind, default_binding, locate

SCRIPT = Path(__file__).with_name("profile_binding.py")
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/profile.example.json"


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profile = self.root / "profile.json"
        self.profile.write_bytes(EXAMPLE.read_bytes())
        self.profile.chmod(0o600)
        self.binding = self.root / "private" / "binding.json"

    def test_default_is_user_private_and_independent_of_working_directory(self):
        with patch("profile_binding.Path.home", return_value=self.root):
            self.assertEqual(default_binding(), self.root / ".codex-top-mode/binding.json")

    def test_another_process_recovers_only_the_location_from_another_directory(self):
        before = self.profile.read_bytes()
        bind(self.binding, self.profile)
        other = self.root / "another-session"
        other.mkdir()
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--binding", str(self.binding), "locate"],
            cwd=other, capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["profilePath"], str(self.profile))
        self.assertEqual(
            json.loads(self.binding.read_text()),
            {"schemaVersion": 1, "profilePath": str(self.profile)},
        )
        self.assertEqual(self.profile.read_bytes(), before)

    def test_missing_binding_does_not_create_setup_or_start_work(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--binding", str(self.binding), "locate"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.binding.parent.exists())
        self.assertEqual(result.stdout, "")

    def test_rebinding_requires_explicit_replace_and_same_profile_is_idempotent(self):
        bind(self.binding, self.profile)
        saved = self.binding.read_bytes()
        bind(self.binding, self.profile)
        self.assertEqual(self.binding.read_bytes(), saved)
        second = self.root / "second.json"
        second.write_bytes(self.profile.read_bytes())
        second.chmod(0o600)
        with self.assertRaises(ValueError):
            bind(self.binding, second)
        self.assertEqual(self.binding.read_bytes(), saved)
        bind(self.binding, second, replace=True)
        self.assertEqual(locate(self.binding)["profilePath"], str(second))

    def test_rejects_profile_or_binding_in_git_even_an_ignored_folder(self):
        repo = self.root / "repo"
        repo.mkdir()
        for marker in ("directory", "worktree-file"):
            with self.subTest(marker=marker):
                git = repo / ".git"
                if marker == "directory":
                    git.mkdir()
                else:
                    git.write_text("gitdir: ../administrative-directory")
                ignored = repo / ".local"
                ignored.mkdir(exist_ok=True)
                inside = ignored / "profile.json"
                inside.write_bytes(self.profile.read_bytes())
                inside.chmod(0o600)
                with self.assertRaises(ValueError):
                    bind(self.binding, inside)
                with self.assertRaises(ValueError):
                    bind(ignored / "binding.json", self.profile)
                self.assertFalse(self.binding.exists())
                if git.is_dir():
                    git.rmdir()
                else:
                    git.unlink()

    def test_symlink_or_moved_into_git_profile_is_not_recovered(self):
        bind(self.binding, self.profile)
        repo = self.root / "repo"
        (repo / ".git").mkdir(parents=True)
        moved = repo / "profile.json"
        self.profile.rename(moved)
        self.profile.symlink_to(moved)
        with self.assertRaises(ValueError):
            locate(self.binding)

    def test_missing_profile_or_invalid_binding_never_falls_back_to_example(self):
        bind(self.binding, self.profile)
        self.profile.unlink()
        with self.assertRaises(OSError):
            locate(self.binding)
        self.binding.write_text('{"schemaVersion": 99, "profilePath": "relative.json"}')
        with self.assertRaises(ValueError):
            locate(self.binding)

    def test_invalid_profile_and_profile_as_binding_are_rejected(self):
        with self.assertRaises(ValueError):
            bind(self.profile, self.profile)
        self.profile.write_text('{}')
        with self.assertRaises(ValueError):
            bind(self.binding, self.profile)
        self.assertFalse(self.binding.exists())

    def test_explicit_replace_can_repair_a_damaged_binding(self):
        bind(self.binding, self.profile)
        self.binding.write_text('{}')
        with self.assertRaises(ValueError):
            bind(self.binding, self.profile)
        bind(self.binding, self.profile, replace=True)
        self.assertEqual(locate(self.binding)["profilePath"], str(self.profile))

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits")
    def test_private_permissions_and_readable_profile_refusal(self):
        bind(self.binding, self.profile)
        self.assertEqual(self.binding.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.binding.parent.stat().st_mode & 0o777, 0o700)
        self.profile.chmod(0o644)
        with self.assertRaises(ValueError):
            locate(self.binding)


if __name__ == "__main__":
    unittest.main()

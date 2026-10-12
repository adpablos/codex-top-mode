import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import capacity_policy
from capacity_policy import action_decision, effective_actions, validate_profile

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/profile.example.json"


def profile():
    return json.loads(EXAMPLE.read_text())


def broken(edit):
    p = profile()
    edit(p)
    return p


class LevelTests(unittest.TestCase):
    def test_example_is_valid(self):
        validate_profile(profile())

    def test_each_level_gives_the_documented_decisions(self):
        expected = {
            "careful": {
                "allowed": {"read", "edit", "checks", "commit"},
                "ask": {"publish_pr", "review", "merge", "install", "access", "redeem_reset"},
            },
            "balanced": {
                "allowed": {"read", "edit", "checks", "commit", "publish_pr", "review"},
                "ask": {"merge", "install", "access", "redeem_reset"},
            },
            "autonomous": {
                "allowed": {"read", "edit", "checks", "commit", "publish_pr", "review", "merge"},
                "ask": {"install", "access", "redeem_reset"},
            },
        }
        for level, decisions in expected.items():
            p = profile()
            p.update(level=level, actions={})
            got = effective_actions(p)
            with self.subTest(level):
                self.assertEqual(set(got), capacity_policy.ACTIONS)
                for decision in ("allowed", "ask"):
                    self.assertEqual(
                        {a for a, d in got.items() if d == decision}, decisions[decision]
                    )
                self.assertEqual(
                    {a for a, d in got.items() if d == "deny"}, {"finance", "destruction"}
                )

    def test_an_exception_wins_over_the_level(self):
        p = profile()
        self.assertEqual(action_decision(p, "notes-app", "publish_pr"), "ask")
        p["actions"] = {"merge": "deny", "destruction": "ask"}
        self.assertEqual(action_decision(p, "notes-app", "merge"), "deny")
        self.assertEqual(action_decision(p, "notes-app", "destruction"), "ask")
        self.assertEqual(action_decision(p, "notes-app", "publish_pr"), "allowed")

    def test_a_saved_reset_is_never_spent_without_asking(self):
        for level in capacity_policy.LEVELS:
            p = profile()
            p.update(level=level)
            self.assertEqual(action_decision(p, "notes-app", "redeem_reset"), "ask")
        with self.assertRaises(ValueError):
            validate_profile(broken(lambda p: p["actions"].update(redeem_reset="allowed")))

    def test_unknown_projects_and_actions_are_denied(self):
        p = profile()
        self.assertEqual(action_decision(p, "client-work", "read"), "deny")
        self.assertEqual(action_decision(p, "notes-app", "deploy"), "deny")


class ValidationTests(unittest.TestCase):
    """Each rule that protects the user rejects its own broken field."""

    def test_an_old_profile_asks_to_set_up_again(self):
        old = {"schemaVersion": 1, "backlog": []}
        with self.assertRaisesRegex(ValueError, "old format"):
            validate_profile(old)

    def test_optional_sections_can_be_left_out(self):
        p = profile()
        for key in ("actions", "excluded", "models"):
            p.pop(key)
        p["projects"]["notes-app"].pop("notes")
        validate_profile(p)
        self.assertEqual(effective_actions(p), capacity_policy.LEVELS["balanced"])

    def test_each_broken_field_is_refused(self):
        notes = lambda p: p["projects"]["notes-app"]  # noqa: E731
        cases = {
            "not an object": [],
            "no version": broken(lambda p: p.pop("schemaVersion")),
            "version as text": broken(lambda p: p.update(schemaVersion="2")),
            "version as boolean": broken(lambda p: p.update(schemaVersion=True)),
            "unknown field": broken(lambda p: p.update(backlog=[])),
            "no approval time zone": broken(
                lambda p: p["authorization"].update(approvedAt="2033-05-18T00:00:00")
            ),
            "no expiry policy": broken(lambda p: p["authorization"].pop("validUntil")),
            "expiry equal to approval": broken(
                lambda p: p["authorization"].update(validUntil=p["authorization"]["approvedAt"])
            ),
            "expiry not a time": broken(lambda p: p["authorization"].update(validUntil="soon")),
            "no source": broken(lambda p: p["authorization"].update(source=" ")),
            "authorization not an object": broken(lambda p: p.update(authorization="yes")),
            "unknown level": broken(lambda p: p.update(level="reckless")),
            "level as a list": broken(lambda p: p.update(level=["balanced"])),
            "unknown action": broken(lambda p: p["actions"].update(deploy="allowed")),
            "unknown decision": broken(lambda p: p["actions"].update(edit="maybe")),
            "decision as a list": broken(lambda p: p["actions"].update(edit=["ask"])),
            "limits not an object": broken(lambda p: p.update(limits=[])),
            "unknown limit": broken(lambda p: p["limits"].update(maximumHour=2)),
            "zero hours": broken(lambda p: p["limits"].update(maximumHours=0)),
            "hours as text": broken(lambda p: p["limits"].update(maximumHours="2")),
            "zero threads": broken(lambda p: p["limits"].update(maximumActiveThreads=0)),
            "threads as boolean": broken(lambda p: p["limits"].update(maximumActiveThreads=True)),
            "implicit weekly stop": broken(
                lambda p: p["limits"].update(stopOnScheduledWeeklyRenewal=None)
            ),
            "no projects": broken(lambda p: p.update(projects={})),
            "project without label": broken(lambda p: notes(p).pop("label")),
            "relative project path": broken(lambda p: notes(p).update(path="projects/notes")),
            "project inside an exclusion": broken(
                lambda p: p["excluded"].append("/home/you/projects")
            ),
            "excluded project itself": broken(
                lambda p: p["excluded"].append("/home/you/projects/notes-app")
            ),
            "relative exclusion": broken(lambda p: p.update(excluded=["client-work"])),
            "no work sources": broken(lambda p: notes(p).update(work=[])),
            "unknown GitHub source": broken(lambda p: notes(p).update(work=["github-issue"])),
            "file outside the project": broken(lambda p: notes(p).update(work=["../PLAN.md"])),
            "absolute work file": broken(lambda p: notes(p).update(work=["/tmp/PLAN.md"])),
            "work source as a list": broken(lambda p: notes(p).update(work=[["ROADMAP.md"]])),
            "negative priority": broken(lambda p: notes(p).update(priority=-1)),
            "priority as boolean": broken(lambda p: notes(p).update(priority=False)),
            "empty notes": broken(lambda p: notes(p).update(notes="")),
            "unknown project field": broken(lambda p: notes(p).update(owner="me")),
            "unknown model tier": broken(lambda p: p["models"]["codex"].update(fast="x")),
            "empty model list": broken(lambda p: p["models"].update(claude={})),
        }
        for name, p in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                validate_profile(p)

    def test_github_sources_are_exact_and_files_stay_inside(self):
        p = profile()
        notes = p["projects"]["notes-app"]
        notes["work"] = ["github-issues", "github-prs", "github-alerts", "docs/PLAN.md"]
        validate_profile(p)


class MainTests(unittest.TestCase):
    def run_main(self, data, *argv):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(data if isinstance(data, str) else json.dumps(data))
            out = io.StringIO()
            args = ["capacity_policy.py", "--profile", str(path), *argv]
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(out):
                capacity_policy.main()
            return json.loads(out.getvalue())

    def test_reports_approval_level_actions_and_one_decision(self):
        p = profile()
        result = self.run_main(p, "--project", "notes-app", "--action", "merge")
        self.assertEqual(result.pop("fingerprint"), capacity_policy.fingerprint(p))
        # The fictional approval starts in 2033, so it is not active yet.
        self.assertEqual(
            result,
            {
                "authorizationActive": False,
                "level": "balanced",
                "actions": effective_actions(p),
                "decision": "ask",
            },
        )
        now = datetime.now(timezone.utc).isoformat()
        p["authorization"].update(approvedAt=now, validUntil=None)
        self.assertTrue(self.run_main(p)["authorizationActive"])

    def test_approval_is_active_from_approval_until_just_before_expiry(self):
        p = profile()
        start = capacity_policy.epoch(p["authorization"]["approvedAt"])
        end = capacity_policy.epoch(p["authorization"]["validUntil"])
        for now, active in ((start - 1, False), (start, True), (end - 1, True), (end, False)):
            clock = patch.object(capacity_policy.time, "time", return_value=now)
            with self.subTest(now=now), clock:
                self.assertEqual(self.run_main(p)["authorizationActive"], active)

    def test_the_fingerprint_changes_with_any_change(self):
        p = profile()
        before = self.run_main(p)["fingerprint"]
        for edit in (
            lambda p: p["limits"].update(maximumHours=1),
            lambda p: p.update(level="autonomous"),
            lambda p: p["projects"]["website"].update(priority=0),
        ):
            changed = profile()
            edit(changed)
            self.assertNotEqual(self.run_main(changed)["fingerprint"], before)

    def test_refuses_an_invalid_profile_or_half_a_question(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as refused:
                self.run_main("not json")
            self.assertEqual(refused.exception.code, 2)
            with self.assertRaises(SystemExit) as old:
                self.run_main({"schemaVersion": 1})
            self.assertEqual(old.exception.code, 2)
            with self.assertRaises(SystemExit):
                self.run_main(profile(), "--action", "merge")
        self.assertIn("Profile refused", stderr.getvalue())
        self.assertIn("Set it up again", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

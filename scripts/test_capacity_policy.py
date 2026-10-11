import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import capacity_policy
from capacity_policy import action_decision, ready_work, validate_profile

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/profile.example.json"


def profile():
    return json.loads(EXAMPLE.read_text())


class ProfileTests(unittest.TestCase):
    def test_example_is_valid_and_offers_only_ready_included_work(self):
        p = profile()
        validate_profile(p)
        self.assertEqual(ready_work(p), ["document-recovery"])

    def test_older_profiles_with_announcement_fields_stay_valid(self):
        p = profile()
        p["authorization"].update(conditionalStart=True, allowUnspecifiedUpcoming=False)
        p["sources"]["announcements"] = ["https://x.com/example_pub"]
        p["limits"]["announcementMaxAgeHours"] = 8
        validate_profile(p)
        self.assertEqual(ready_work(p), ["document-recovery"])

    def test_action_policy_preserves_exclusions_and_separate_review_merge_gates(self):
        p = profile()
        self.assertEqual(action_decision(p, "sample-notes", "edit"), "allowed")
        for action in ("review", "merge", "redeem_reset"):
            self.assertEqual(action_decision(p, "sample-notes", action), "ask")
        self.assertEqual(action_decision(p, "client-example", "edit"), "deny")
        self.assertEqual(action_decision(p, "unregistered", "edit"), "deny")
        self.assertEqual(action_decision(p, "sample-notes", "unknown"), "deny")
        p["actions"]["redeem_reset"] = "allowed"
        with self.assertRaises(ValueError):
            validate_profile(p)

    def test_busy_owners_and_active_slots_cannot_be_reassigned(self):
        p = profile()
        task = copy.deepcopy(p["backlog"][0])
        task.update(id="another-task", owner="second-owner", priority=2)
        p["backlog"].append(task)
        p["backlog"][0]["status"] = "in_progress"
        self.assertEqual(ready_work(p), ["another-task"])
        p["limits"]["maximumActiveThreads"] = 1
        self.assertEqual(ready_work(p), [])

    def test_each_active_task_counts_even_with_a_shared_owner(self):
        p = profile()
        p["backlog"][0]["status"] = "in_progress"
        second = copy.deepcopy(p["backlog"][0])
        second["id"] = "second-active-task"
        p["backlog"].append(second)
        pending = copy.deepcopy(second)
        pending.update(id="pending-task", status="pending", owner="another-owner")
        p["backlog"].append(pending)
        self.assertEqual(ready_work(p), [])

    def test_unready_blocked_and_finished_tasks_do_not_become_busywork(self):
        for change in (
            {"ready": False},
            {"blocker": "awaiting sample input"},
            {"status": "done"},
        ):
            p = profile()
            p["backlog"][0].update(change)
            self.assertEqual(ready_work(p), [])

    def test_invalid_profiles_are_refused(self):
        def broken(edit):
            p = profile()
            edit(p)
            return p

        for p in (
            broken(lambda p: p["authorization"].update(approvedAt="2033-05-18T00:00:00")),
            broken(lambda p: p["authorization"].pop("validUntil")),
            broken(lambda p: p["sources"].update(backlog=[])),
            broken(lambda p: p["limits"].update(maximumHours=0)),
            broken(lambda p: p["backlog"][0].pop("blocker")),
            broken(lambda p: p.update(excludedProjects=["unregistered"])),
        ):
            with self.assertRaises(ValueError):
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

    def test_reports_approval_ready_work_and_one_decision(self):
        p = profile()
        result = self.run_main(p, "--project", "sample-notes", "--action", "merge")
        # The fictional approval starts in 2033, so it is not active yet.
        self.assertEqual(
            result,
            {"authorizationActive": False, "readyWork": ["document-recovery"], "decision": "ask"},
        )
        now = datetime.now(timezone.utc).isoformat()
        p["authorization"].update(approvedAt=now, validUntil=None)
        self.assertTrue(self.run_main(p)["authorizationActive"])

    def test_refuses_an_invalid_profile_or_half_a_question(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as refused:
                self.run_main("not json")
            self.assertEqual(refused.exception.code, 2)
            with self.assertRaises(SystemExit):
                self.run_main(profile(), "--action", "merge")
        self.assertIn("Profile refused", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()


class ValidationTests(unittest.TestCase):
    """Each rule that protects the user rejects its own broken field."""

    def test_each_broken_field_is_refused(self):
        def broken(edit):
            p = json.loads(EXAMPLE.read_text())
            edit(p)
            return p

        cases = {
            "not an object": [],
            "version as text": broken(lambda p: p.update(schemaVersion="1")),
            "expiry equal to approval": broken(
                lambda p: p["authorization"].update(validUntil=p["authorization"]["approvedAt"])
            ),
            "expiry not a time": broken(lambda p: p["authorization"].update(validUntil="soon")),
            "no backlog sources": broken(lambda p: p["sources"].update(backlog=[])),
            "project without label": broken(lambda p: p["projects"]["sample-notes"].pop("label")),
            "exclusions not a list": broken(lambda p: p.update(excludedProjects="client-example")),
            "unregistered exclusion": broken(lambda p: p.update(excludedProjects=["unknown"])),
            "no actions": broken(lambda p: p.update(actions={})),
            "unknown decision": broken(lambda p: p["actions"].update(edit="maybe")),
            "unknown action": broken(lambda p: p["actions"].update(deploy="allowed")),
            "zero hours": broken(lambda p: p["limits"].update(maximumHours=0)),
            "zero threads": broken(lambda p: p["limits"].update(maximumActiveThreads=0)),
            "threads as text": broken(lambda p: p["limits"].update(maximumActiveThreads="2")),
            "threads as boolean": broken(lambda p: p["limits"].update(maximumActiveThreads=True)),
            "missing model tier": broken(lambda p: p["limits"]["modelTiers"].pop("difficult")),
            "duplicate task": broken(lambda p: p["backlog"].append({**p["backlog"][0]})),
            "unregistered task project": broken(
                lambda p: p["backlog"][0].update(project="unknown")
            ),
            "unknown status": broken(lambda p: p["backlog"][0].update(status="blocked")),
            "negative priority": broken(lambda p: p["backlog"][0].update(priority=-1)),
        }
        for name, p in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                validate_profile(p)

    def test_ready_work_fills_exactly_the_free_slots(self):
        p = json.loads(EXAMPLE.read_text())
        for number in (2, 3):
            extra = copy.deepcopy(p["backlog"][0])
            extra.update(id=f"task-{number}", owner=f"owner-{number}", priority=number)
            p["backlog"].append(extra)
        self.assertEqual(ready_work(p), ["document-recovery", "task-2"])

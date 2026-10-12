import json
import unittest

from usage_monitor import (
    expiry_advice,
    snapshot,
)

START = 2000000000


def reading(used=17, resets=3, now=START, reset_at=START + 86400, grants=None):
    payload = {
        "accountId": "synthetic-private-identity",
        "rateLimitsByLimitId": {
            "codex": {
                "primary": {
                    "usedPercent": used,
                    "windowDurationMins": 10080,
                    "resetsAt": reset_at,
                },
                "credits": {"balance": "secret"},
            }
        },
        "rateLimitResetCredits": {
            "availableCount": resets,
            "credits": [
                {"id": "synthetic-credit-id", "status": "available", "grantedAt": t}
                for t in (grants or [])
            ],
        },
    }
    return snapshot(payload, now)


class MonitorTests(unittest.TestCase):
    def test_no_identifiers_or_balance_are_persisted(self):
        text = json.dumps(reading(grants=[START - 100]))
        for forbidden in (
            "synthetic-private-identity",
            "synthetic-credit-id",
            "secret",
            "accountId",
        ):
            self.assertNotIn(forbidden, text)

    def test_documented_minimum_native_payload_retains_available_expiration(self):
        payload = {
            "rateLimitResetCredits": {
                "availableCount": 1,
                "credits": [
                    {
                        "status": "available",
                        "grantedAt": START - 100,
                        "expiresAt": START + 100,
                    },
                    {
                        "status": "consumed",
                        "grantedAt": START - 200,
                        "expiresAt": START + 200,
                    },
                ],
            }
        }
        current = snapshot(payload, START)
        self.assertEqual(current["grantTimes"], [START - 100])
        self.assertEqual(expiry_advice(current)["dueExpirations"], [START + 100])
        self.assertEqual(expiry_advice(current)["expiryCoverage"], "complete")

    def test_expiry_warning_uses_actual_seven_day_boundary(self):
        observation = reading()
        observation["resetExpirations"] = [
            {"grantedAt": START - 100, "expiresAt": START + 7 * 86400},
            {"grantedAt": START - 200, "expiresAt": START + 8 * 86400},
            {"grantedAt": START - 300, "expiresAt": START - 1},
        ]
        advice = expiry_advice(observation)
        self.assertEqual(advice["dueExpirations"], [START + 7 * 86400])
        self.assertEqual(advice["nextWarningAt"], START + 86400)
        self.assertEqual(advice["expiryCoverage"], "partial")

    def test_missing_expirations_are_unknown_not_thirty_days(self):
        advice = expiry_advice(reading())
        self.assertEqual(advice["dueExpirations"], [])
        self.assertIsNone(advice["nextWarningAt"])
        self.assertEqual(advice["expiryCoverage"], "partial")

    def test_expired_or_consumed_rows_are_not_available_warnings(self):
        observation = snapshot(
            {
                "rateLimitResetCredits": {
                    "availableCount": 0,
                    "credits": [
                        {"status": "consumed", "expiresAt": START + 10},
                        {"status": "available", "expiresAt": START + 20},
                    ],
                }
            },
            START,
        )
        advice = expiry_advice(observation)
        self.assertEqual(advice["dueExpirations"], [])
        self.assertEqual(advice["expiryCoverage"], "complete")

    def test_null_count_does_not_claim_complete_expiry_inventory(self):
        advice = expiry_advice(snapshot({}, START))
        self.assertEqual(advice["expiryCoverage"], "unknown")

    def test_duplicate_expiration_details_do_not_prove_complete_coverage(self):
        observation = reading(resets=2)
        row = {"grantedAt": START - 1, "expiresAt": START + 100}
        observation["resetExpirations"] = [row, row]
        advice = expiry_advice(observation)
        self.assertEqual(advice["expiryCoverage"], "partial")
        self.assertEqual(advice["dueExpirations"], [START + 100])


class BoundaryTests(unittest.TestCase):
    def test_snapshot_keeps_0_and_100_and_drops_impossible_values(self):
        def windows(used):
            limits = {"primary": {"usedPercent": used, "windowDurationMins": 10080}}
            return snapshot({"rateLimits": limits}, START)["windows"]

        self.assertTrue(windows(0) and windows(100))
        self.assertFalse(windows(-1) or windows(101))
        for count, kept in ((2, 2), (-1, None), (1.5, None)):
            payload = {"rateLimitResetCredits": {"availableCount": count}}
            self.assertEqual(snapshot(payload, START)["availableResets"], kept)


if __name__ == "__main__":
    unittest.main()

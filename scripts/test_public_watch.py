import contextlib
import copy
import html
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from public_watch import (
    LiteralReader,
    PublicRedirects,
    SourceError,
    main,
    poll,
    profile_posts,
    read_public,
    validate_config,
    verify_embed,
)

START = 2000000000
SOURCE = "https://x.com/example_pub"
ROOT = Path(__file__).resolve().parents[1]


def config():
    value = json.loads((ROOT / "examples/watch.example.json").read_text())
    value["enabled"] = True
    return value


def post(index=1, at=START - 10, text="Synthetic future announcement"):
    return {
        "sourceUrl": SOURCE + "/status/" + str(10000000000 + index),
        "author": SOURCE,
        "publishedAt": at,
        "text": text,
    }


def page(p=None, author="example_pub", quote=None, quoted_id=None):
    p = p or post()
    tweet = {
        "__typename": "Tweet",
        "rest_id": p["sourceUrl"].split("/")[-1],
        "core": {"user_results": {"result": {"core": {"screen_name": author}}}},
        "details": {
            "created_at_ms": int(p["publishedAt"] * 1000),
            "full_text": p["text"],
        },
    }
    if quote:
        tweet["quoted_tweet"] = {"details": {"created_at_ms": START * 1000, "full_text": quote}}
    if quoted_id:
        tweet["quoted_tweet_results"] = {
            "rest_id": quoted_id,
            "result": {"__typename": "Tweet", "rest_id": quoted_id},
        }
    entry = {
        "content": {
            "__typename": "TimelineTimelineItem",
            "content": {"tweet_results": {"result": tweet}},
        },
        "entry_id": "tweet-" + tweet["rest_id"],
    }
    import re

    raw = re.sub(r'"([A-Za-z_]+)":', r"\1:", json.dumps(entry, separators=(",", ":")))
    return (
        "<script>$R[0]="
        + raw.replace("content:{__typename:", "content:$R[1]={__typename:", 1)
        + "</script>"
    )


def embed(p=None):
    p = p or post()
    date = datetime.fromtimestamp(p["publishedAt"], timezone.utc)
    day = date.strftime("%B") + f" {date.day}, {date.year}"
    return {
        "author_url": SOURCE,
        "provider_name": "X",
        "provider_url": "https://x.com",
        "type": "rich",
        "html": "<blockquote><p>"
        + html.escape(p["text"])
        + '</p><a href="'
        + p["sourceUrl"]
        + '">'
        + day
        + "</a></blockquote>",
    }


def reader(posts):
    return lambda source, now, limit: copy.deepcopy(posts)


class ParserTests(unittest.TestCase):
    def test_primary_literals_and_quoted_post_do_not_confuse_identity_or_time(self):
        expected = post(text='Primary "text" with <tag> and Unicode ñ')
        self.assertEqual(
            profile_posts(page(expected, quote="Unrelated quoted text"), SOURCE, START),
            [expected],
        )

    def test_no_supported_entries_and_changed_sibling_format_are_unknown(self):
        for body in (
            "<html>Log in</html>",
            "<html></html>",
            page() + 'entry_id:"tweet-10000000002"',
            page().replace("TimelineTimelineItem", "ChangedFormat"),
        ):
            with self.assertRaises(SourceError):
                profile_posts(body, SOURCE, START)

    def test_author_future_time_blank_text_and_conflicting_identity_fail_closed(self):
        for body in (
            page(post(at=START + 1)),
            page(post(text=" ")),
            page() + page(post(text="Conflicting text")),
        ):
            with self.assertRaises(SourceError):
                profile_posts(body, SOURCE, START)

    def test_literal_parser_refuses_expressions_and_cycles_without_execution(self):
        for source in (
            "function(){return 1}",
            "$R[0]=$R[0]",
            "process.exit(0)",
            '"unterminated',
        ):
            with self.assertRaises(SourceError):
                LiteralReader(source).value(0)

    def test_valid_foreign_timeline_posts_are_filtered_without_blocking_own_posts(self):
        body = page() + page(post(2), author="other_pub")
        self.assertEqual(profile_posts(body, SOURCE, START), [post()])
        with self.assertRaises(SourceError):
            profile_posts(page(author="bad/author"), SOURCE, START)

    def test_official_embed_matches_author_post_text_and_day(self):
        verify_embed(json.dumps(embed()), post())
        old = embed()
        old.update(
            author_url="https://twitter.com/example_pub",
            provider_name="Twitter",
            provider_url="https://twitter.com",
        )
        verify_embed(json.dumps(old), post())
        for change in (
            {"author_url": "https://x.com/other_pub"},
            {"author_url": "https://x.com.attacker.invalid/example_pub"},
            {"provider_url": "https://attacker.invalid"},
            {"type": "link"},
            {"html": "<p>Other text</p>"},
            {"html": embed()["html"].replace("May 18, 2033", "May 19, 2033")},
        ):
            payload = embed()
            payload.update(change)
            with self.assertRaises(SourceError):
                verify_embed(json.dumps(payload), post())

    def test_embed_accepts_real_publisher_case_and_tracking_parameters(self):
        p = post()
        document = embed(p)
        document["author_url"] = "https://twitter.com/Example_Pub"
        document["html"] = document["html"].replace(
            p["sourceUrl"],
            p["sourceUrl"].replace(SOURCE, "https://twitter.com/Example_Pub")
            + "?ref_src=synthetic",
        )
        verify_embed(json.dumps(document), p)
        document["html"] = document["html"].replace("Example_Pub", "other_pub")
        with self.assertRaises(SourceError):
            verify_embed(json.dumps(document), p)

    def test_incomplete_http_read_is_recorded_without_losing_other_publishers(self):
        from http.client import IncompleteRead

        from public_watch import fetch

        other = "https://x.com/another_pub"
        cfg = config()
        cfg["publishers"].append(other)
        state, _ = poll(cfg, {}, START, reader([post()]))
        with patch("public_watch.urllib.request.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.side_effect = IncompleteRead(b"partial", 100)

            def read(source, now, limit):
                if source == SOURCE:
                    fetch(source)
                return [post()]

            now = START + 4 * 3600
            state, output = poll(cfg, state, now, read)
            self.assertEqual(output, [])
            record = state["publishers"][SOURCE]
            self.assertEqual(record["coverage"], "unknown")
            self.assertEqual(record["failureSince"], now)
            self.assertEqual(record["lastSuccessfulCheckAt"], START)
            self.assertEqual(state["publishers"][other]["lastSuccessfulCheckAt"], now)
            state, output = poll(cfg, state, now + 8 * 3600, read)
            self.assertEqual([entry["kind"] for entry in output], ["coverage_failure"])

    def test_public_reader_cross_checks_embed_and_never_classifies_or_authorizes(self):
        calls = []

        def get(url):
            calls.append(url)
            return page() if url == SOURCE else json.dumps(embed())

        self.assertEqual(read_public(SOURCE, START, 5, get), [post()])
        self.assertEqual(len(calls), 2)
        self.assertIn("omit_script=true", calls[1])
        self.assertNotIn("mechanism", read_public(SOURCE, START, 5, get)[0])

    def test_quote_embed_suffix_is_cross_checked_without_leaking_parser_metadata(self):
        payload = embed()
        link = "https://t.co/synthetic"
        payload["html"] = payload["html"].replace("</p>", f' <a href="{link}">{link}</a></p>')
        calls = []

        def get(url):
            calls.append(url)
            return page(quoted_id="10000000009") if url == SOURCE else json.dumps(payload)

        self.assertEqual(read_public(SOURCE, START, 5, get), [post()])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("_quotedPostId", read_public(SOURCE, START, 5, get)[0])

    def test_quote_suffix_exception_does_not_accept_other_text_or_unanchored_urls(self):
        link = "https://t.co/synthetic"
        quoted = dict(post(), _quotedPostId="10000000009")
        valid_suffix = f' <a href="{link}">{link}</a>'
        for suffix in (
            " " + link,
            valid_suffix + " extra words",
            valid_suffix.replace("t.co", "attacker.invalid"),
            valid_suffix.replace(f">{link}<", ">Different label<"),
            valid_suffix.replace(f'href="{link}"', 'href="https://t.co/other"'),
        ):
            payload = embed()
            payload["html"] = payload["html"].replace("</p>", suffix + "</p>")
            with self.assertRaises(SourceError):
                verify_embed(json.dumps(payload), quoted)
        payload = embed()
        payload["html"] = payload["html"].replace("</p>", valid_suffix + "</p>")
        with self.assertRaises(SourceError):
            verify_embed(json.dumps(payload), post())
        payload["html"] = payload["html"].replace("Synthetic", "Different")
        with self.assertRaises(SourceError):
            verify_embed(json.dumps(payload), quoted)

    def test_doubtful_primary_quote_identity_remains_unknown(self):
        for body in (
            page(quoted_id="invalid"),
            page(quoted_id=post()["sourceUrl"].split("/")[-1]),
            page(quoted_id="10000000009").replace(
                'result:{__typename:"Tweet",rest_id:"10000000009"}',
                'result:{__typename:"Tweet",rest_id:"10000000008"}',
            ),
        ):
            with self.assertRaises(SourceError):
                profile_posts(body, SOURCE, START)

    def test_redirects_allow_only_same_host_or_exact_official_embed_alias(self):
        import urllib.request

        redirects = PublicRedirects()
        req = urllib.request.Request("https://publish.twitter.com/oembed?url=public")
        allowed = redirects.redirect_request(
            req, None, 301, "Moved", {}, "https://publish.x.com/oembed?url=public"
        )
        self.assertEqual(allowed.full_url, "https://publish.x.com/oembed?url=public")
        for url in (
            "http://publish.x.com/oembed",
            "https://attacker.invalid/oembed",
            "https://publish.x.com/login",
            "https://user@publish.x.com/oembed",
        ):
            with self.assertRaises(SourceError):
                redirects.redirect_request(req, None, 301, "Moved", {}, url)


class WatchTests(unittest.TestCase):
    def test_disabled_example_never_reads_or_emits(self):
        c = config()
        c["enabled"] = False
        _, output = poll(c, {}, START, lambda *args: self.fail("Unexpected HTTP"))
        self.assertEqual(output, [])

    def test_baseline_is_quiet_then_only_new_verified_posts_emit_once(self):
        state, output = poll(config(), {}, START, reader([post()]))
        self.assertEqual(output, [])
        self.assertEqual(state["publishers"][SOURCE]["coverage"], "partial")
        new = post(2, START + 1000)
        state, output = poll(config(), state, START + 14400, reader([new, post()]))
        self.assertEqual([p["sourceUrl"] for p in output], [new["sourceUrl"]])
        self.assertEqual(output[0]["kind"], "needs_interpretation")
        self.assertNotIn("announcementStatus", output[0])
        state, output = poll(config(), state, START + 28800, reader([new, post()]))
        self.assertEqual(output, [])

    def test_not_due_or_stale_read_makes_no_request_and_cannot_rewind_state(self):
        state, _ = poll(config(), {}, START, reader([post()]))
        next_check = state["publishers"][SOURCE]["nextCheckAt"]
        for now in (START - 1, START, next_check - 1):
            new, output = poll(config(), state, now, lambda *args: self.fail("Unexpected HTTP"))
            self.assertEqual(new, state)
            self.assertEqual(output, [])

    def test_bounded_tolerance_prevents_scheduler_jitter_from_skipping_a_cycle(self):
        interval = config()["intervalHours"] * 3600
        slot = (START // interval) * interval
        calls = []

        def read(source, now, limit):
            calls.append(now)
            return [post(at=slot - 1)]

        state, _ = poll(config(), {}, slot + 5, read)
        # Saved deadlines from older ledgers do not override the actual attempt.
        state["publishers"][SOURCE]["nextCheckAt"] = slot + interval + 5
        state, output = poll(config(), state, slot + interval + 2, read)
        self.assertEqual(calls, [slot + 5, slot + interval + 2])
        self.assertEqual(output, [])
        self.assertEqual(state["publishers"][SOURCE]["nextCheckAt"], slot + 2 * interval + 2 - 1800)
        saved = copy.deepcopy(state)
        for now in (
            slot + interval + 1,
            slot + interval + 3,
            saved["publishers"][SOURCE]["nextCheckAt"] - 1,
        ):
            state, output = poll(config(), state, now, read)
            self.assertEqual(state, saved)
            self.assertEqual(output, [])
        self.assertEqual(len(calls), 2)

    def test_delayed_check_reads_once_without_catchup_requests(self):
        interval = config()["intervalHours"] * 3600
        slot = (START // interval) * interval
        state, _ = poll(config(), {}, slot + 5, reader([post(at=slot - 1)]))
        calls = []

        def read(source, now, limit):
            calls.append(now)
            return [post(at=slot - 1)]

        state, output = poll(config(), state, slot + 3 * interval + 9, read)
        self.assertEqual(calls, [slot + 3 * interval + 9])
        self.assertEqual(output, [])
        self.assertEqual(state["publishers"][SOURCE]["nextCheckAt"], slot + 4 * interval + 9 - 1800)

    def test_near_boundary_late_then_early_schedule_does_not_skip(self):
        interval = config()["intervalHours"] * 3600
        boundary = (START // interval) * interval
        times = [boundary + interval + 60, boundary + 2 * interval - 60]
        calls = []

        def read(source, now, limit):
            calls.append(now)
            return [post(at=boundary - 1)]

        state, _ = poll(config(), {}, times[0], read)
        state, output = poll(config(), state, times[1], read)
        self.assertEqual(calls, times)
        self.assertEqual(output, [])
        self.assertEqual(state["publishers"][SOURCE]["lastAttemptAt"], times[1])
        saved = copy.deepcopy(state)
        state, output = poll(config(), state, boundary + 2 * interval + 20, read)
        self.assertEqual(state, saved)
        self.assertEqual(output, [])
        self.assertEqual(calls, times)

    def test_old_unseen_posts_after_baseline_cannot_trigger(self):
        state, _ = poll(config(), {}, START, reader([post()]))
        _, output = poll(config(), state, START + 14400, reader([post(5, START - 1)]))
        self.assertEqual(output, [])

    def test_bounded_retention_and_watermark_prevent_replay_after_eviction(self):
        c = config()
        c.update(maximumPosts=20, retainedIds=20)
        state, _ = poll(c, {}, START, reader([post()]))
        for cycle in range(1, 5):
            posts = [post(cycle * 20 + i, START + cycle * 14400 - 100 + i) for i in range(20)]
            state, output = poll(c, state, START + cycle * 14400, reader(posts))
            self.assertEqual(len(output), 20)
        self.assertEqual(len(state["publishers"][SOURCE]["seenPosts"]), 20)
        self.assertEqual(len(state["recentSignals"]), 50)
        _, output = poll(c, state, START + 5 * 14400, reader([post(20, START + 14400 - 100)]))
        self.assertEqual(output, [])

    def test_sustained_failure_alerts_once_then_recovery_still_seeds_baseline(self):
        def fail(*args):
            raise SourceError("Synthetic format change")

        state = {}
        for seconds in (0, 14400):
            state, output = poll(config(), state, START + seconds, fail)
            self.assertEqual(output, [])
        state, output = poll(config(), state, START + 28800, fail)
        self.assertEqual([s["kind"] for s in output], ["coverage_failure"])
        state, output = poll(config(), state, START + 43200, fail)
        self.assertEqual(output, [])
        state, output = poll(config(), state, START + 57600, reader([post()]))
        self.assertEqual([s["kind"] for s in output], ["coverage_recovered"])
        self.assertEqual(state["publishers"][SOURCE]["coverage"], "partial")

    def test_failed_checks_keep_last_success_and_empty_discovery_is_unknown(self):
        state, _ = poll(config(), {}, START, reader([post()]))
        state, output = poll(config(), state, START + 14400, reader([]))
        self.assertEqual(output, [])
        self.assertEqual(state["publishers"][SOURCE]["coverage"], "unknown")
        self.assertEqual(state["publishers"][SOURCE]["lastSuccessfulCheckAt"], START)

    def test_late_visible_posts_newer_than_installation_are_not_lost(self):
        state, _ = poll(config(), {}, START, reader([post()]))
        newer = post(2, START + 3600)
        state, _ = poll(config(), state, START + 14400, reader([newer]))
        late = post(3, START + 3500)
        state, output = poll(config(), state, START + 28800, reader([newer, late]))
        self.assertEqual([p["sourceUrl"] for p in output], [late["sourceUrl"]])
        _, output = poll(config(), state, START + 43200, reader([late]))
        self.assertEqual(output, [])

    def test_first_failed_read_preserves_install_time_and_subsequent_new_posts(self):
        def fail(*args):
            raise SourceError("Synthetic failure")

        state, _ = poll(config(), {}, START, fail)
        self.assertEqual(state["publishers"][SOURCE]["baselineAt"], START)
        new = post(2, START + 100)
        state, output = poll(config(), state, START + 14400, reader([new, post()]))
        self.assertEqual([p["sourceUrl"] for p in output], [new["sourceUrl"]])
        self.assertEqual(state["publishers"][SOURCE]["baselineAt"], START)

    def test_malformed_saved_state_refuses_without_mutating_or_reading(self):
        for state in (
            {"version": True},
            {"publishers": {SOURCE: []}},
            {"publishers": {SOURCE: {"baselineAt": "invalid"}}},
            {"recentSignals": {}},
            {"publishers": {SOURCE: {"seenPosts": []}}},
        ):
            original = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                poll(config(), state, START, lambda *args: self.fail("Unexpected HTTP"))
            self.assertEqual(state, original)

    def test_config_rejects_authority_spoofs_and_unsafe_cadence(self):
        for change in (
            {"version": True},
            {"enabled": "yes"},
            {"publishers": ["https://x.com.attacker.invalid/example_pub"]},
            {"publishers": ["https://user:password@x.com/example_pub"]},
            {"intervalHours": 0},
            {"maximumPosts": 100},
            {"failureNoticeHours": 4, "intervalHours": 8},
        ):
            c = config()
            c.update(change)
            with self.assertRaises(ValueError):
                validate_config(c)

    def test_transition_does_not_mutate_callers_state(self):
        state = {}
        poll(config(), state, START, reader([post()]))
        self.assertEqual(state, {})

    def test_cli_disabled_is_silent_and_does_not_create_watch_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            run = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/public_watch.py"),
                    "--once",
                    "--config",
                    str(ROOT / "examples/watch.example.json"),
                    "--state",
                    str(state),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "")
            self.assertFalse(state.exists())

    def test_enabled_cli_writes_private_state_and_remains_quiet_at_baseline(self):
        import os

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            conf = Path(directory) / "watch.json"
            conf.write_text(json.dumps(config()))
            arguments = [
                "watch",
                "--once",
                "--config",
                str(conf),
                "--state",
                str(state),
            ]
            original = poll

            def synthetic(c, saved, now):
                return original(c, saved, START, reader([post()]))

            with (
                patch.object(sys, "argv", arguments),
                patch("public_watch.poll", synthetic),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                main()
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(os.stat(state).st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(state.read_text())["publishers"][SOURCE]["baselineAt"], START
            )

    def test_missing_platform_lock_support_refuses_cleanly(self):
        arguments = ["watch", "--once", "--config", "unused", "--state", "unused"]
        with (
            patch.object(sys, "argv", arguments),
            patch.dict(sys.modules, {"fcntl": None}),
            contextlib.redirect_stderr(io.StringIO()) as output,
            self.assertRaises(SystemExit) as error,
        ):
            main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("macOS/Linux", output.getvalue())

    def test_existing_lock_prevents_second_writer_without_reading_or_replacing_state(
        self,
    ):
        import fcntl

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text('{"sentinel":"unchanged"}')
            with open(str(state) + ".lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                run = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(ROOT / "scripts/public_watch.py"),
                        "--once",
                        "--config",
                        str(ROOT / "examples/watch.example.json"),
                        "--state",
                        str(state),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(run.returncode, 2)
            self.assertEqual(state.read_text(), '{"sentinel":"unchanged"}')


if __name__ == "__main__":
    unittest.main()

# Reset announcements and conditional start (optional, Codex)

This is an optional, experimental add-on. Top Mode works without it: you can
start manually, or follow the quota suggestion in the [skill](../SKILL.md).

OpenAI staff sometimes announce Codex usage resets on X. Two helpers let a Codex
user react to that:

- [`public_watch.py`](../scripts/public_watch.py) reads the public posts of the
  publishers you approve and reports only **new** posts that need a look. It makes
  no model calls and stays silent when nothing changed. X often blocks anonymous
  reads, so coverage is partial and failures are reported as unknown coverage.
- [`capacity_policy.py`](../scripts/capacity_policy.py) checks a verified
  announcement against your private profile and decides whether a conditional
  start is allowed. It only applies when your profile sets
  `authorization.conditionalStart: true`.

News never grants permission by itself, and the watcher never starts work.
A host scheduler (for example a Codex automation) must run the watcher; nothing
here installs one. The profile fields are described in the
[profile contract](profile-contract.md).

## Neutral event

A verified event contains no prompt, instructions or account data:

```json
{
  "sourceUrl": "https://example.org/official-capacity-news/new-announcement",
  "publishedAt": "2033-05-18T01:00:00Z",
  "mechanism": "banked_reset",
  "announcementStatus": "upcoming",
  "expectedResetAt": null,
  "verification": {
    "method": "primary_source_read",
    "verifiedAt": "2033-05-18T01:05:00Z"
  }
}
```

Mechanisms are `banked_reset`, `automatic_restoration`, `mixed`, `unspecified`.
The publisher must be in the human-approved sources. The operator must read the
actual primary post, verify author, publication time and mechanism, and label
whether its text unambiguously announces a future event or says it has applied.
Do not infer `upcoming` from a title such as “Day 6 / Reset”, surrounding
context or a secondary forecast. A public post is
not proof of eligibility or replenishment for the local account. Unknown
mechanisms stay advisory unless the human profile explicitly allows verified
upcoming unspecified events. `expectedResetAt` is optional: omit it or leave it
null when the primary source gives no exact reset time. Verified upcoming news
can still activate a fixed window. If a timestamp is supplied, it must be valid,
future and verified from the primary announcement; contradictory or invalid
timestamps are rejected, never repaired by guessing. The precise publication
time and freshness still need verification. Applied automatic or
mixed announcements stay advisory too; check the actual account rather than
launching work after a restoration that may already have happened. A banked credit alone is not
replenished weekly quota.

Only publication after human approval and within the configured freshness
limit can trigger conditional work. Use at most eight hours of freshness for
an eight-hour policy. Verification must follow publication and cannot be in
the future. Canonical publisher URLs ignore query/fragment variants and are
recorded monotonically: a duplicate cannot restart a finished window or extend
an active one. X/Twitter post URLs also normalize media suffixes and account case;
ambiguous path segments are rejected. Publications at or before the latest window
start stay advisory even under a different URL. New announcements seen during an
active window are consumed without extending it. An event supplied when an old
window ends is evaluated against the resulting inactive state. If that event
does not start a new window, the stop decision and its reason remain visible;
`announcementStatus` reports the event outcome separately. Temporary missing
telemetry or unavailable work may be retried against the same still-fresh event
before any window starts.

The script validates the envelope; it does not independently verify a post or
its author. Never set `primary_source_read` from a snippet, secondary summary,
failed retrieval or unknown coverage. A forged verified flag is not authority.

## Public reading and discovery

For a known primary URL, use permitted host tools to read the public page. For
X, an alternative public publisher-owned route is the official oEmbed endpoint
at `https://publish.twitter.com/oembed`, with the canonical post URL in its
URL-encoded `url` parameter and `omit_script=true`. Read the returned text and
metadata without executing embedded scripts. Use public unauthenticated reads;
do not import cookies or introduce an account client.

Verify the publisher/author URL and post identity against the approved source.
Keep the original canonical post URL as `sourceUrl` for source checks and
deduplication, not the embed endpoint URL. HTML metadata or an embed containing
only a calendar date cannot establish a precise `publishedAt`, freshness or
publication after human approval; do not substitute midnight or retrieval time.
A known-URL reading route is not a guarantee of future availability. Failed
reads, including 403s, stay unknown unless another permitted primary route
succeeds. Ambiguous publication time or upcoming/applied classification remains
advisory or leads to an explicitly requested manual run. An unspecified reset
hour alone does not make clearly future primary news ambiguous.

Visible public timeline entries and third-party histories may discover candidate
links. Treat them as partial discovery, not verified events or full timeline
coverage; verify each candidate at the primary source. Forecasts cannot trigger
work. Official incident history feeds concern incidents and do not establish a
reliable schedule of future reset promotions. No feed or continuous monitoring
is assumed here, and this package adds no scraper, daemon or transport.

## Public watch operations

Prepare private storage outside Git worktrees, such as `~/.codex-top-mode/`,
with owner-only access. After human approval, adapt the disabled watch example
there; preserve any existing configuration and journal. Watch permission is
independent from permission to execute top mode. Run from the package root:

```sh
python3 -B scripts/public_watch.py --once \
  --config "$HOME/.codex-top-mode/watch.json" --state "$HOME/.codex-top-mode/watch-state.json"
python3 -B scripts/public_watch.py --status \
  --config "$HOME/.codex-top-mode/watch.json" --state "$HOME/.codex-top-mode/watch-state.json"
```

`--once` reads when the configured interval has elapsed, allowing scheduler
jitter of one eighth of the interval, capped at 30 minutes. A four-hour schedule
therefore tolerates runs up to 30 minutes early regardless of their UTC phase;
`nextCheckAt` is the earliest eligible time after the last actual attempt. Repeated
or stale calls before that time make no request. Larger delays or clock errors
remain the scheduler's responsibility. No scheduler is created.
`--status` reads saved coverage without HTTP. Installation time is fixed before the first read;
successful reads seed the known IDs. Outputs
are `needs_interpretation`, `coverage_failure` or `coverage_recovered`; no output
means no new **verified visible** signal, not “there are no announcements”. State
keeps bounded IDs, a replay floor for evicted posts, and the latest 50 receipts.
Newly visible posts after installation can be received out of order while within
that retention horizon; older evicted posts cannot replay.
This is a discovery receipt, not the neutral activation event: the coordinator
must verify/classify it and remains the sole writer of its own work policy/state.

The watch reads public X profile data and the publisher's official embed using
standard-library HTTP. It never executes page JavaScript. Author, original post
identity, publication day and primary text must match. For a primary post with a
verified quoted-post identity, the embed may append one anchored `t.co` link;
other additions or changed content remain unknown. The first enabled check fixes
the installation timestamp; existing posts do not trigger. If that first read
fails, the timestamp is preserved so later verified posts are not discarded. It outputs only newly verified public
posts needing interpretation, or one notice after eight hours of failed coverage.
Unchanged checks are quiet. The agent interprets only new posts, verifies upcoming
versus applied and mechanism from primary text, then checks permission, freshness,
ready work and native quota before using the capacity preflight.

The script makes **no model calls**. A scheduler that wakes an agent/model every
four hours still has that cost; an empty result should end quickly. A receipt
on stdout or in private state does **not** wake or resume an agent by itself.
Test the host's scheduling and notification hook before promising that behavior.
Without a supported scheduler/hook, the explicit alternative is a manual check.

## Local preflight

```sh
python3 -B scripts/capacity_policy.py \
  --profile /chosen/private/profile.json \
  --state /chosen/private/state.json \
  --event /chosen/private/public-event.json \
  --observed-at ACTUAL_ISO_UTC
```

Provide the sanitized native usage payload through stdin. Omit `--event` for
subsequent polls. The state file can be absent; its parent must already exist.
Writes are atomic and private. The caller must enforce one writer for a state
file and bind readings to the same host/account; change of binding requires a
new baseline. Never relabel saved telemetry as a fresh native reading.

A start requires applicable human conditional authority, fresh verified news,
ready work and available weekly telemetry. Known exhausted windows block a
start. Low weekly usage alone neither proves replenishment nor blocks useful
work on a valid future announcement. Already confirmed native replenishment
prevents activation from news published before that confirmation.
The deadline is start plus `maximumHours`, clamped to an explicit authorization
expiry when present. Consent until revocation still creates a fixed-duration
window on every activation. Grants and duplicate news cannot extend it.
The preflight returns task IDs and a decision, not running workers or approval
for their actions. Exhausted or missing telemetry and stale observations suppress
new candidates during an active window without extending its deadline. Before
dispatch, refresh owners, all available thread slots, model availability and
the action-specific gates.

Off-schedule weekly replenishment requires two native readings 20 seconds to
30 minutes apart through the existing observer. New profile windows also detect
a positive decrease smaller than five points toward at most 2% usage when both
weekly reset timestamps are known and the new timestamp moves forward. Both
fresh readings must retain that decrease and timestamp advancement against the
original anchor. A low reading alone, a missing or unchanged reset timestamp,
or a timestamp change without a decrease is insufficient. Legacy monitors
without the explicit `detectLowUsageRenewalShift` flag retain their existing
strong-decrease requirement. If scheduled renewal stopping is enabled, the initial known weekly renewal also stops new assignments when
due, even with missing later telemetry. This is a conservative time stop, not
an assertion that account replenishment was observed. Preserve the earlier
fixed deadline if it comes first. Stop new assignments, ask active owners for
a bounded checkpoint, and report the actual stop reason.

Legacy callers may keep using `usage_monitor.py` and its explicit normal/
conditional deadlines. Do not adopt a legacy active window into a new profile;
close or checkpoint its owner first. The new preflight creates no conditional
extension and defaults to no automatic redemption.


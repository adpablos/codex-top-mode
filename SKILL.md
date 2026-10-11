---
name: codex-top-mode
description: Prepare a portable capacity profile, run human-requested bounded top mode, or preflight verified reset news against an approved local backlog.
---

Use this skill for capacity advice, explicitly requested manual top mode, or
previously authorized conditional work. The [README](README.md) is the human
entry point; [AGENTS.md](AGENTS.md) routes use versus maintenance. Read linked
files explicitly when given a URL; report what you actually loaded. Explain setup
in the user's language and prepare private files yourself.
Public news supplies information, never execution authority. Keep quality,
current owners and useful backlog outcomes ahead of quota consumption.

## Choose the mode and profile

For advice, read current usage and public sources; do not start intensive work.
For either execution mode, verify a human-approved private profile defining sources,
projects/exclusions, backlog, actions, models and limits. Read the
[profile/event contract](references/profile-contract.md) and adapt the
[fictional example](examples/profile.example.json); its disabled activation and
sample authorization are not permission. No personal path, dashboard, project
manager or cloud service is required. Copy/export only the versioned skill
folder; keep real profiles, observations and state outside it.

Before preparing a new setup or executing a later session, recover the user's
profile with `python3 -B scripts/profile_binding.py locate` from this package.
At approved first setup, save the binding as described in the
[private binding contract](references/profile-contract.md#private-profile-binding).
Read the located profile and check its approved scope, validity and current
host/action gates. A short start request inherits that setup; it does not widen
permissions. Missing, invalid or conflicting bindings require focused setup or
repair; never silently use an example, another profile or conversation memory.

Refresh backlog objectives, benefit, completion criteria, current owner,
readiness and blockers from approved local sources. Prioritize existing pending
closures. Count all active threads, preserve active owners, and check each
project/action against `action_decision(profile, project, action)` plus its
current native and state-specific approvals. Review and merge are configurable
separate actions. Never create work or redundant checks just to spend quota.

## Coordinate existing work

The current agent is the sole coordinator and writer of its private work-policy
state. Inspect approved sources, refresh priorities and owners, and reuse a
permitted existing session before proposing another. Do not take over busy work.
Delegate only bounded independent work that adds value, through supported tools
and within the existing thread limit; if unavailable, work serially. Model tiers
are choices resolved in the receiving client, not automatic routing by these scripts.
At checkpoints, verify owner outcomes before updating the approved backlog/state;
retain unfinished work, blockers and the next owner. Read/unread and archive state
are never task-completion evidence. Answer setup/status/stop requests using actual
loaded files, configuration, deadlines and tested scheduling/notification evidence.

## Obtain actual capacity

Check whether the host exposes native capacity observation such as
`get_usage_limits`. If absent, disclose that weekly replenishment cannot be
observed reliably; offer only supervised work with an agreed time deadline. Do
not add an authentication client or claim automatic weekly stopping.
When available, read actual UTC time and fresh native usage. Prefer
`rateLimitsByLimitId.codex`; use the legacy bucket only when the map is absent.
Consumed quota is `usedPercent`; remaining is `100 - usedPercent`. Identify
weekly (10080 minutes) and five-hour (300 minutes) windows by duration. Missing
windows are unknown. Use authoritative `rateLimitResetCredits.availableCount`;
detail rows may be partial. Use actual expiry timestamps, never a presumed
credit lifetime. Do not read authentication files or add an account client.

Preserve native `rateLimitsByLimitId.codex` (or legacy `rateLimits`) and
`rateLimitResetCredits` nesting when supplying stdin. Retain only window
percentage/duration/reset time, available count, and credit `status`, grant and
expiry times (Unix seconds). `snapshot(payload, observed_at)` in
[scripts/usage_monitor.py](scripts/usage_monitor.py) removes identities,
balances and credentials. Save only sanitized readings and minimal state in a
private ignored location; use a new baseline if the host/account binding changes.

## Manual top mode

An explicit human request can start a bounded manual run without news. Prepare
its approved profile and private observer state as described in the
[manual-run contract](references/profile-contract.md#manual-run). Keep the
manual state separate from the event ledger; preserve owners and news dedup.
Check the profile's action ceilings, ready work and all active slots before
each assignment. Only propose model changes supported by the receiving client.

## Optional public watch

After separate human permission, prepare the disabled watch example in private
storage. Test [scripts/public_watch.py](scripts/public_watch.py) once, then ask
the host's supported scheduler to run `--once` every four hours. Read the
[watch operations](references/profile-contract.md#public-watch-operations) for commands
and coverage/receipt semantics; the README explains platform limits.
Do not create a daemon, install services or promise wakeup from stdout alone.
The script makes no model calls; a scheduler that wakes a model still does.
Interpret only new `needs_interpretation` signals, verifying primary future/applied
classification and mechanism before constructing an activation event. The watcher
cannot grant authority or trigger work and never writes the coordinator's state.

## Verify public news and preflight locally

Read the actual post from the profile's approved primary sources and verify
publisher, publication time, mechanism and whether it is upcoming or applied.
For a known URL, try a permitted public page read or the publisher's official
embed as described in the [source-reading contract](references/profile-contract.md#public-reading-and-discovery).
A 403 from one reader does not establish failure of every public route. Failed
primary reads leave coverage unknown until another permitted primary read
succeeds. Snippets and secondary summaries cannot activate work. Check the
account separately; do not infer eligibility or attribute quota changes from
timing alone.

The active local agent can read a supplied URL, verify the human profile, obtain
fresh native usage and refresh work before calling
[scripts/capacity_policy.py](scripts/capacity_policy.py). Optional cloud inbox
adapters follow the same checks; they are not needed for a direct URL.
The contract describes the event mapping, local CLI and dependency boundaries.
This skill implements no scheduler, cloud account polling or mailbox transport;
do not claim operational delivery or continuous coverage without testing them.

Conditional activation requires news published after authorization, configured
freshness, ready work and actual available quota. Duplicate URL variants cannot
restart or extend a window; a grant does not replenish weekly usage. Applied
automatic-restoration news stays advisory. Unspecified mechanisms need an
explicit profile opt-in and primary text unambiguously announcing a future
reset. The exact reset time is optional: leave it unknown unless published;
an explicit timestamp must be valid and future. Verify upcoming versus applied
from the primary text, never from a title such as “Day 6 / Reset” alone. Low
usage alone does not prove restoration or veto useful future-announcement work.
For ambiguous news, keep advice or offer a separately requested manual run.
Returned task
IDs are candidates; the operator still checks thread slots, owners, available
models and permissions before dispatch. Use the configured economical tier for
bounded verifiable work and stronger tiers for ambiguity or failed verification.

## Watch and stop

Poll with the real native reading time. `capacity_policy.py` freezes the earlier
of the configured duration and any explicit human authorization expiry. Consent
until revocation still creates a fixed-duration window each time. No later news or
credit extends it. Two fresh readings 20 seconds to 30 minutes apart confirm a
strong off-schedule weekly decrease. New profile windows also confirm a small
positive decrease toward at most 2% only when both readings retain a known
forward shift of the weekly reset timestamp. A low reading or timestamp shift
alone is insufficient; legacy monitors keep their strong-decrease requirement.
If the profile requires it, the initial scheduled weekly renewal stops
assignments when due even if telemetry later fails. That time stop is not proof
of observed replenishment. Changed operating authority stops an active window too.

Legacy integrations may call `observe(monitor, snapshot)` or the existing
`usage_monitor.py --state ... --observed-at ...` CLI with an already authorized
`usageMonitor` envelope. Preserve its baseline, fixed `effectiveStopAt`, and
separately authorized `bankedStopAt`; a late grant never revives an expired
window. The new profile preflight creates no conditional extension. Do not
silently adopt a legacy active window as a new authorization.

These helpers observe only when called; they do not schedule or wake the agent.
Check time and fresh quota before assignments and at bounded checkpoints. On
resume after interruption, check the frozen deadline and permissions first.
At any stop, cease new assignments, let owners deliver a bounded checkpoint,
gather outcomes and pause only the intensive follow-up. Keep writes and specific
approval gates intact. Never redeem a reset automatically; every attempt needs
current explicit human confirmation and supported-tool eligibility. Use one
idempotency key per logical redemption attempt; uncertain retries reuse it.
Refresh native usage afterward and distinguish applied, already applied,
unavailable and unknown outcomes without guessing success.

## Advisory expiry and closure

Use `expiry_advice(snapshot)` to find credits within seven days of their actual
expiry. Alert once per expiry, then at most once within 24 hours if still
available. Record notice thresholds after delivery and revalidate availability;
missing detail does not prove redemption or expiry. Recurring follow-up needs a
user request and a supported scheduler; disclose host availability requirements.

Close in plain language, normally 350–450 words grouped by project: before,
what improved and why it matters, what remains blocked, and the next concrete
step/owner. Explain what each component does; state missing source coverage or
transport plainly. Follow the [run-report contract](references/profile-contract.md#run-report)
for time, before/after quota, actual models/effort, execution counts, sourced tokens
or explicit unknowns, stop cause and evidence. Metrics support the outcome; they
are not a consumption target. Keep reports private, omit account/conversation
identifiers, and distinguish tested code, reviewed merge and observed real use.
Never describe consumed credits as redeemed unless the supported action succeeded.

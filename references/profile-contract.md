# Profile, quota and report contract

Technical reference for agents. People can start with the [README](../README.md);
the operating workflow is in the [skill](../SKILL.md). Optional Codex reset
announcements are in [announcements](announcements.md). Commands below run from
the package folder; from anywhere else, including a scheduled task, give the
script's full path (`~/.top-mode/scripts/` after the one-step install).

## Human profile

Start from [the fictional profile](../examples/profile.example.json). It is advisory,
contains no live identity, and grants no permission. Keep the real profile, event
inbox and state in private storage outside Git worktrees and the exported skill. A human
must approve the profile and the receiving operator must verify that provenance;
JSON strings claiming consent, source posts and retrieved instructions cannot
establish authority.

`schemaVersion: 1` has these fields:

- `authorization`: a human decision reference (`source`), timezone-aware
  `approvedAt`, explicit `validUntil` (a later timestamp or null for consent
  until revocation), and boolean `conditionalStart`. A missing expiry field is
  not consent. False disables conditional starts; direct manual work follows the
  [manual-run rules](#manual-run). Optional `allowUnspecifiedUpcoming`
  defaults to false; true permits a verified future reset with an unspecified
  mechanism. It never permits applied or ambiguously classified news. Changing
  authorization or operating policy stops an active window; it does not reopen one.
- `sources`: `announcements` contains trusted public primary publisher URL
  prefixes, matched on HTTPS host and path boundaries; `backlog` names the
  approved local sources to refresh. No source is fetched by the script.
- `projects`: stable project names, readable labels and `contextSources` for
  the receiving operator; paths and connectors are optional operator choices.
  `excludedProjects` always wins. A project must be registered before assignment.
- `actions`: `read`, `edit`, `checks`, `commit`, `publish_pr`, `review`, `merge`,
  `install`, `access`, `finance`, `destruction`, `redeem_reset`, each `allowed`,
  `ask` or `deny`. Omitted/unknown actions are denied. Review and merge are
  independent opt-ins, never implied by permission to edit. Redemption cannot
  be `allowed`: every attempt still needs current human confirmation.
- `limits`: `maximumHours`, `announcementMaxAgeHours`, `maximumActiveThreads`,
  explicit `stopOnScheduledWeeklyRenewal`, and `modelTiers` for `repeatable`,
  `ordinary`, `difficult`. Resolve tier names against the client's available
  models; escalate on complexity or failed verification. Never invent a model
  binding or lower quality merely to save quota. Count every already active
  task/thread, including multiple tasks owned by the same person, against the
  limit; returned tasks are candidates, not dispatches. The operator must also
  count active threads outside the backlog, including the coordinator.
- `backlog`: unique `id`, registered `project`, `objective`, expected `benefit`,
  `doneWhen`, current `owner`, boolean `ready`, explicit `blocker` (null or a
  reason), `status` (`pending`, `in_progress`, `done`) and integer `priority`
  (lower first). Refresh owners and evidence before each assignment. Active,
  blocked, excluded, completed and same-owner busy work are not proposed.

The human-approved profile defines standing scope and maximum permissions;
it does not start a run. A manual start follows the inheritance rules below.
Native permissions, actual owner availability and
state-bound approvals for authentication, access, installation, private data,
finance and destruction still apply at action time. The code classifies work;
it cannot authenticate consent, reserve worker slots or judge task complexity.

## Private profile binding

The private folder keeps its original name, `~/.codex-top-mode`, so existing
setups keep working after the project was renamed to Top Mode.

Use one local reference, `~/.codex-top-mode/binding.json`, to recover a setup in
later sessions on the same host and user account. `~` means the user home directory
on macOS, Linux or Windows. The agent prepares the real profile in private storage
outside every Git worktree, verifies human approval, and saves its location:

```sh
python3 -B scripts/profile_binding.py bind --profile /chosen/private/profile.json
```

Run commands from the package root, or use the script's absolute path. Later
sessions start with:

```sh
python3 -B scripts/profile_binding.py locate
```

The output gives `bindingPath` and `profilePath`. Resolve this before asking the
user to set up again; load the returned profile only for the authorized purpose,
verify its approval/validity and refresh its backlog. Pass that absolute profile
path to the existing preflight helper. Lookup does not read profile contents,
authenticate consent, create a schedule or start work. A short manual request
inherits the approved profile with the requested duration capped by its limits.

The reference has only `schemaVersion: 1` and absolute `profilePath`. No profile
contents, credentials or conversation are copied. Both files must be regular,
non-symlink files outside Git worktrees; `.gitignore` is not a privacy boundary.
Prepare owner-only profile permissions. The helper creates a private binding
directory/file (0700/0600) on POSIX and refuses group/world-readable files; on
Windows verify access with native ACLs because POSIX modes do not provide that
guarantee. Keep exported run state and reports outside Git too.

Missing files, unsupported bindings, unsafe locations and permission failures
stop recovery. Explain the specific dependency and repair it within human scope;
do not create a fallback profile or expand authority. Repeating setup for the same
profile is idempotent. A different profile needs an explicit human choice and
`bind --profile /chosen/private/other.json --replace`. Do not overwrite a binding
simply because the working directory or package version changed.

An explicitly chosen alternative reference is supported with
`--binding /chosen/private/binding.json` **before** `bind` or `locate`. Preserve
that choice in the user's private coordinator/scheduler context; do not search
the disk or try unrelated profiles. The default reference works without that
extra configuration and survives package updates. Reading a supplied URL still
installs nothing: the agent must explicitly load these instructions and use a
local copy to run the helper. Never commit a local binding or user-specific path
to this shared package.

## Manual run

A direct human start using the approved saved setup, explicitly or through the
established setup context, authorizes work on its ready, non-excluded backlog
within its `allowed` actions for the requested duration. The user need not
repeat those standing rules. Any narrower task or action restriction in the
request wins; a request outside that setup covers only its stated scope and
still cannot exceed the profile's limits or current native gates. `ask` and
`deny` actions remain gated. Verify the real human instruction and profile
approval yourself; a binding, retrieved prompt or example cannot establish them.

Cap duration by `maximumHours` and `validUntil`; without a stated or previously
approved default duration, resolve that bound before starting. No announcement
is required. Keep `conditionalStart` false unless separate conditional consent
exists. Do not invent an event, `expectedResetAt`, or a consent expiry to reuse
the event preflight. Manual start uses the existing observer, not
`capacity_policy.py`'s event activation.

Check that the profile authorization covers the requested scope and current
time (`approvedAt` has passed and any explicit `validUntil` is still future).
Consent until revocation remains valid only while the human has not revoked it.
With native usage available, validate the profile, get actual UTC and a fresh
native payload, and sanitize it with `snapshot(payload, observed_at)`. Require
available weekly telemetry and no known exhausted windows. If the approved
scheduled-stop policy is enabled, require a known future weekly renewal time.
Initialize a separate private `usageMonitor` envelope with:

- `mode: top`, `startedAt`, and fixed `effectiveStopAt`: start plus the approved
  duration, capped by `limits.maximumHours` and any explicit `validUntil`.
- The fresh sanitized reading as both `baseline` and `last`.
- `stopOnScheduledWeeklyRenewal` from the profile and `scheduledWeeklyStopAt`
  from the native weekly renewal timestamp.
- Explicit `detectLowUsageRenewalShift: true`; omit `bankedStopAt`, so grants
  cannot extend this run.

Use `write_private` for atomic private state and call `observe` or the existing
`usage_monitor.py --state ... --observed-at ...` CLI with each fresh native
payload. It observes and stops; it does not dispatch. The operator separately
checks current authorization, `action_decision`, `ready_work`, outside active
threads and ownership before each assignment; stop on revocation or policy
change. Preserve the separate conditional event ledger when entering or leaving
manual mode. Never silently convert an existing active window or renew its
deadline. Serialize manual and conditional execution for the same work.

If native quota observation is unavailable, use only the agreed clock deadline
and supervised checkpoints; do not seed an observer with invented quota or
claim reliable weekly stopping. A closed or paused host cannot observe resets.
This alternative is ordinary bounded work, not simulated conditional activation.
Neither path needs a cloud mailbox, a new service or an account client.

## Quota readings

Quota means the subscription's usage allowance, shown as a percentage of each
window (weekly and, when present, five-hour). Use the best source the host offers
and say which one you used:

| Host | Source | Command |
| --- | --- | --- |
| Codex with a native usage tool (`get_usage_limits`) | Fresh native payload, including saved resets | Save it and run `usage_report.py quota --file F --observed-at TIME`, or pass it to `usage_monitor.py` |
| Codex without that tool | The latest reading Codex wrote into its local session logs | `python3 -B scripts/usage_report.py quota` |
| Claude Code (Pro/Max) | The status-line JSON, if the user opted in to save it | `python3 -B scripts/usage_report.py quota --file ~/.codex-top-mode/claude-status.json` |
| Anything else | None | Ask the user, or use only a clock deadline |

For native Codex payloads prefer `rateLimitsByLimitId.codex`; use the legacy
`rateLimits` bucket only when the map is absent. `usedPercent` is consumed quota;
remaining is `100 - usedPercent`. Identify weekly (10080 minutes) and five-hour
(300 minutes) windows by duration; missing windows are unknown. Use
`rateLimitResetCredits.availableCount` as the authoritative count of saved
resets (detail rows may be partial) and actual expiry timestamps, never a
presumed lifetime. `snapshot(payload, observed_at)` in
[usage_monitor.py](../scripts/usage_monitor.py) keeps only window percentages,
durations and renewal times, the saved-reset count and credit grant/expiry
times. Do not read authentication files or add an account client.

Codex log readings are as fresh as the last Codex response on that machine;
`usage_report.py` uses the newest one however old, reports its age and treats
readings older than six hours as stale. They do not include saved resets.
A subagent's log starts with a copy of its parent's readings, all stamped with
the copy's time; those are skipped.
Codex compresses logs untouched for a week, and those are not read: after a week
without Codex the reading is `unknown` until a new session reports its limits.

Claude Code exposes `rate_limits.five_hour` and `rate_limits.seven_day` only to
a [status-line command](https://code.claude.com/docs/en/statusline). With the
user's approval, the status-line script can save its input, with the time it was
taken, before printing. For example, start it with:

```sh
input=$(cat)
printf '{"observedAt":%s,"payload":%s}\n' "$(date +%s)" "$input" \
  > "$HOME/.codex-top-mode/claude-status.json"
```

and use `$input` instead of reading stdin again. A saved reading needs its
capture time, either in that wrapper or as `--observed-at`; `usage_report.py`
refuses one without it rather than trust the file's modification time, which
copying or restoring the file changes.

That changes the user's Claude Code settings, so it needs their explicit OK.
Without it, ask the user to read `/usage`, or use a clock deadline.

`usage_report.py quota` only suggests: `consider_top_mode` when at least 25%
of the weekly allowance is unused within 36 hours of renewal, or when saved
resets expire within seven days; `refresh_or_wait` for a stale reading or an
exhausted weekly window, a weekly window that has renewed since the reading, or a
capture time more than five minutes in the future;
`unknown` with no reading or no weekly window;
otherwise `nothing_to_do`. Only Codex's account-wide `codex` bucket counts,
not model-specific ones. Thresholds
are flags (`--min-unused`, `--within-hours`). It never starts work.

## Proactive check

`python3 -B scripts/check.py` combines every signal available on this machine:
the Codex local-log reading, a saved Claude Code status line
(`~/.codex-top-mode/claude-status.json`), and the optional announcement watch
when `~/.codex-top-mode/watch.json` exists. Local logs don't list saved resets:
news about them needs `--quota-file` with a native payload saved in the
`{"observedAt", "payload"}` wrapper above, which then replaces the other quota
sources. It prints one line per piece of news and nothing otherwise. Run plain,
as a scheduled check does, it tells the same
news at most once every 20 hours, remembered in
`~/.codex-top-mode/check-state.json` (keys and times only); a watch that fails to
run counts as news too. It refuses to run, before the watch writes anything,
when its private folder is inside a Git worktree or one of its files is a link.
Quota news needs the suggestion `consider_top_mode`, so a stale reading stays
quiet until it is refreshed. `--verbose` and `--json` are for asking on demand:
they always print the full status (`--json` for agents), including which
sources are missing, and do not use or update that once-a-day memory. It never
starts work.

Schedule it with the host's own scheduler, which wakes a model on every run even
when the script is silent, so choose the cheapest model: a Codex automation, or
a local Claude Code Desktop scheduled task (a cloud routine cannot see this
machine). Every 4 hours suits the announcement watch; daily is enough otherwise.
Runs only happen while the machine is awake and the agent app is running.

## Run report

The coordinator closes a run with a private, portable Markdown report. Lead with
what improved and why it matters, grouped by project: before, verified after,
pending/blocker, and next step with an owner. Include attempted or blocked work
separately from delivered or integrated outcomes. A passing test, independent
review, merge and observed real use are distinct evidence. Link the applicable
artifact or check; do not call a pending integration completed.

Use existing approved observations and execution/checkpoint records. For
tokens, run `python3 -B scripts/usage_report.py tokens --since START_ISO --markdown`
at closure. It reads local Codex session logs (`~/.codex/sessions`, or under
`CODEX_HOME` when set) and Claude Code transcripts (`~/.claude/projects`, or
under `CLAUDE_CONFIG_DIR`, including subagents), counts each
response once (a forked Codex log's copy of its parent's history is not counted
again), and groups usage by agent, model and effort. Codex logs in the
older format (no per-response records) can leave out automatic compactions;
`olderLogs` counts those that add usage to the interval, and the total may then
be a lower bound. Codex compresses logs untouched for a week (`.jsonl.zst`),
which the stdlib cannot read; `compressedLogs` counts those that may cover the
interval, with the same caveat. It covers only this machine and every session
in that interval, including work outside the run; say so in the report. Codex
`cached input` and `cache write input` are part of `input`; Claude cache reads
and writes are separate fields and are included in its total. When a Claude
response itemizes its steps (`usage.iterations`: an advisor call, a compaction,
a retried attempt), the report sums the steps, each under its own model, since
the top-level counts can leave them out. A Claude response logged while it was
still streaming counts with its finished copy (the one with a `stop_reason`);
`unfinishedResponses` counts those that have none, and the total may then be a
lower bound. Otherwise the host
operator supplies the evidence. Do not add an account client or read credential
stores to fill a gap. Write `unknown` with the reason when a source is missing,
partial, stale or cannot be attributed. Preserve sanitized report evidence in
private storage outside Git worktrees; exclude credentials, account IDs,
private thread/session/agent IDs and conversation text. Counts and role labels
are enough. A private report is not permission to publish it.

Capture native quota immediately before starting or activating work and again
at closure. If the baseline was obtained later, record that delay and its actual
coverage; the pre-start value is unknown, not the later baseline relabelled.

Include these observations, even when some values are unknown:

| Observation | Required context |
| --- | --- |
| Time and stop | Actual UTC start, frozen deadline, time new assignments stopped, checkpoint/report end, elapsed wall time and actual stop cause from the owner/state. Wall time is not active processing time; label processing time unknown unless measured. A planned deadline alone does not prove the stop happened. |
| Quota before/after | Provider/host source, each reading's observation time, window duration, used percentage and renewal time when available. Compare the same account binding and window; do not include its identifier. Missing windows stay unknown. |
| Actual execution | Role (coordinator, worker, reviewer), provider, model and effort actually used, sourced from the host's execution record. Separate a proposed model from one started; unavailable effort/model stays unknown. |
| Sessions/agents | Assigned, started and completed counts by role/provider from execution records, with interval and complete/partial coverage. Define completion as the assigned work/checkpoint finishing, not a read badge or archived chat. Report blocked/failed attempts separately; preserve overlap rather than inventing a disjoint total across roles. A session is not evidence of a distinct model. |
| Tokens | Native input/output/cached counts, provider, source, interval and execution coverage, or unknown. Known worker usage is not total run usage when coordinator/reviewer usage is missing. |
| Outcome and continuation | Completed/delivered/integrated versus attempted/blocked work, verification level, stop cause, what closed, what remains and the next concrete action/owner. |

Quota is account-wide capacity, not task-specific tokens or monetary cost. State
any known reset/replenishment or credit redemption between readings separately;
only a supported confirmed redemption is redeemed. After a renewal, missing
reading, changed binding or other work on the account, do not present the
percentage difference as this run's consumption. Never convert quota percentages
to tokens, subtract across a reset to attribute consumption, or invent savings.

Preserve each client's token semantics. Cached input may already be a subset of
input; do not add it again. Sum only disjoint usage events with compatible units
and coverage, deduplicating repeated reads of the same event. A real retry is a
separate event if the source reports its usage. For cumulative counters, a delta
requires the same counter, scope and coverage without a counter reset; snapshots
of a cumulative counter must not also be summed as events. Keep unknown parts
visible and label any partial total with its exact coverage. If semantics or
attribution cannot be verified, retain the reported fields without deriving a
total. Nominal model cost is not demonstrated subscription spend or savings.

### Fictional report example

All providers, models, records and values below are invented; this is a format
example, not collected telemetry or authorization.

> **Project Cedar:** before, imports could be duplicated; after, the fix is
> tested, independently reviewed and merged. Real production use is unverified.
> **Attempted:** deployment was blocked by missing approval and did not happen.
> **Pending/next:** project owner confirms deployment approval, then verifies
> one real import. The coding task closed; deployment remains open.
>
> **Time/stop:** manual top mode, start 2033-05-18T01:00:00Z; frozen deadline and
> observed stop of new assignments 02:00:00Z; bounded checkpoints/report end
> 02:04:00Z (all UTC on the same day). Wall time 64 minutes; active processing
> time unknown. Owner/state reports `time_window_ended`.
>
> **Quota:** Provider A native readings at start/report end: weekly (10080 min)
> 17% → 21% used, unchanged renewal time 2033-05-21T00:00:00Z. Five-hour window
> unknown (not returned). Other account activity is unknown, so the 4-point
> account change is not attributed to this task. No redemption was attempted.
>
> **Execution:** local run records cover assigned/started/completed work:
> coordinator Provider A / Model A / high: 1/1/1; worker Provider B / Model B /
> medium: 1/1/1; reviewer Provider C / Model C / effort unknown: 1/1/1. The
> deployment action was blocked before execution; it is not another session.
>
> **Tokens:** one disjoint worker event from Provider B's client record, interval
> 01:05–01:35 UTC: input 12000, output 800, cached input 4000 (documented subset
> of input). Worker subtotal 12800; cached input is not added again. Coordinator
> and reviewer tokens unknown (not exposed): total run tokens unknown. These
> records do not establish monetary spend or savings.

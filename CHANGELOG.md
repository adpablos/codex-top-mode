# Changelog

User-visible changes integrated into the repository. Dates identify changes,
not a tagged release or evidence of live installation.

## 2026-10-12

- Guided setup with a smaller profile (`schemaVersion: 2`). The agent looks at
  the folders you point it to, proposes your projects and where their pending
  work lives (GitHub issues, pull requests and security alerts, or files such as
  `ROADMAP.md`), and asks only what it can't find out. You pick one of three
  permission levels (careful, balanced by default, or autonomous) and can change
  single actions on top. The profile no longer holds a task list or run state,
  and models per agent are optional. A profile in the old format is refused with
  a request to set up again; the agent carries over its projects, exclusions and
  limits. `capacity_policy.py` no longer prints `readyWork`; it prints the
  level and the resulting actions.
- New rules for a run: commit only on a working branch; when the agent can't see
  whether a task's owner is busy, it asks or only reads; it reports work outside
  the run that it comes across without touching it; and the report proposes
  setup changes, applied only with your approval.

- Renamed the project to Quota Coach (repository `adpablos/quota-coach`, skill
  `quota-coach`, suggested folder `~/.quota-coach`), because it now also tells
  you whether your plan fits, not only how to spend spare quota. Top Mode stays
  as the name of its bounded run on your priorities, so "Start Top Mode" works
  as before. The private folder stays `~/.codex-top-mode`, so saved setups keep
  working. To update an existing install, ask your agent to update Top Mode, or
  run `git -C ~/.top-mode pull && python3 ~/.top-mode/scripts/install.py`: it
  adds the `quota-coach` skill and removes its old `top-mode` link.
- The plan report no longer guesses why a second weekly meter appears: one
  account's sessions can alternate between two meters for a while.
- Added `usage_report.py plan`: is your Codex plan enough? It rebuilds your
  weekly windows from Codex's local logs and says whether the plan has been
  enough, short, or enough only thanks to early renewals, with the evidence:
  peak use per window, how often the limit was reached and how often the same
  use would have run out without early renewals. Top Mode runs still count as
  your own use. Codex only for now.
- `usage_report.py plan` also replays the same use on the other Codex plans,
  with their monthly prices, says when a cheaper plan would have been enough
  every week, and warns of a coming change to your plan, even with little
  history, such as the end of the grandfathered Pro 200 size. Sizes and prices live in
  `references/plans.json` with their sources and check date.

## 2026-10-11

- Reset announcements now only notify. The watch and `check.py` report a new
  post and the agent reads it and tells you what it says; only you start a run.
  Removed the automatic start on announcements and its policy code, and saved
  resets that appear during a run no longer extend its deadline. Existing
  profiles stay valid; their announcement fields are ignored.
  `scripts/capacity_policy.py` is now a small profile check that prints whether
  the approval is active, the ready work and, if asked, one action's decision.
- Added one-step install (`scripts/install.py`) that makes Top Mode a skill in
  Codex and Claude Code, and `scripts/check.py`, a quiet check that combines
  quota, expiring saved resets and announcements, speaks only when there is
  something new and is meant to run on the agent's own scheduler.
- Lowered the minimum to Python 3.9, so the Python that ships with macOS works.
  CI now checks lint, format and workflow security, runs the tests on Python
  3.13 and on macOS's own Python 3.9, enforces 85% coverage, verifies
  documentation links and that documented script flags exist, and reports one
  `all checks` result to require before merging.
- Added the [vision and principles](references/vision.md) that guide every change.
- Renamed the project to Top Mode (repository `adpablos/top-mode`, skill
  `top-mode`). The private folder stays `~/.codex-top-mode` so saved setups
  keep working.
- Rewrote the README, AGENTS.md and skill in plain language around four jobs:
  set up, check, run and report. Top Mode now targets Codex, Claude Code and
  similar agents; announced Codex resets are an optional add-on with their own
  [guide](references/announcements.md). Removed the unimplemented cloud mailbox
  description.
- Added `scripts/usage_report.py`: a quota suggestion (unused weekly allowance
  near renewal, expiring saved resets) from Codex local logs, a native Codex
  payload or a saved Claude Code status line, and token totals per agent, model
  and effort from local Codex and Claude Code logs for run reports. Claude
  advisor calls count under the advisor's model. It honors
  `CODEX_HOME` and `CLAUDE_CONFIG_DIR`, and a saved reading must carry its
  capture time (the file's modification time is not trusted). A reading
  without a weekly window is `unknown`, never `nothing_to_do`. Totals that may
  miss usage (older-format Codex logs, which can leave out automatic
  compactions, compressed Codex logs, which the stdlib cannot read, or Claude
  responses logged before they finished) are marked as a possible lower bound.
- Added a [fictional run report](examples/report.example.md).

- Added a private profile reference that setup saves and later sessions recover,
  with a short activation request, explicit profile replacement and refusal of
  Git worktree locations. Package updates preserve personal settings.

- Simplified first-time setup and the coordinator/status/stop explanation with
  an accessible diagram and fictional conversation. Distinguished included files,
  active work, announcement watch and saved reset reminders. Added a short agent
  entry point and moved maintenance/technical watch details to their guides.

- Added the portable profile/skill for bounded manual work and verified
  conditional preflight, with deadlines, ownership checks, explicit permissions
  and native quota stopping. Added the optional public watcher with partial
  discovery, quiet unchanged checks and replay protection ([PR #1](https://github.com/adpablos/codex-top-mode/pull/1)).
- Added the owner-dispatched read-only maintainer review workflow, including
  credential-output rejection and bounded publication. It requires a separately
  configured personal credential and real runtime verification; package users
  do not need it ([PR #2](https://github.com/adpablos/codex-top-mode/pull/2)).
- Defined a [portable run report](references/profile-contract.md#run-report)
  linking useful outcomes with sourced time, quota, model/effort, execution
  counts and tokens or explicit unknowns. No telemetry collector was added.
- Documented how a maintainer configures, dispatches and verifies the optional
  review workflow, including human credential entry and separate merge authority.

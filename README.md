# Top Mode

[![Checks](https://github.com/adpablos/top-mode/actions/workflows/tests.yml/badge.svg)](https://github.com/adpablos/top-mode/actions/workflows/tests.yml)

**Use the AI subscription you already pay for, on purpose and without losing track.**

Coding-agent subscriptions come with weekly limits. Whatever you don't use before
the limit renews is gone. Top Mode is a skill for your agent (Codex, Claude Code
or any agent that can read files and run Python) that turns that spare capacity
into work you actually care about:

- **It tells you when it's worth it.** Your weekly allowance renews soon and a
  lot is still unused, saved resets are about to expire, or a reset was announced.
- **It works on your priorities, with your rules.** You decide the projects, what
  to leave out, and what the agent may do alone or must ask first.
- **It stops on time.** Every run has a deadline that nothing can extend.
- **It tells you what happened.** Each run ends with a short report: what changed,
  what is pending, and what it used (quota before and after, tokens per model).

Downloading it starts nothing and changes no settings. It is a set of instructions
plus small Python scripts with no dependencies. [MIT license](LICENSE).

## Get started

**1. Install.** Ask your agent (Codex or Claude Code):

```text
Install Top Mode from https://github.com/adpablos/top-mode
```

It runs two commands you can also run yourself:

```sh
git clone https://github.com/adpablos/top-mode ~/.top-mode &&
  python3 ~/.top-mode/scripts/install.py
```

This makes Top Mode available as a skill in every new Codex and Claude Code
session. Your agent may ask you to approve running the install script; that is
expected. Update with `git -C ~/.top-mode pull`; undo with
`python3 ~/.top-mode/scripts/install.py --remove`.

**2. Set up, once.** In a new session, say *"Help me set up Top Mode."* The agent
asks about your projects and priorities, what to leave out, what it may do
without asking, and a default time limit. It shows you the setup in plain words
and saves it, after your approval, in a private file outside any Git repository.
You never need to edit JSON.

**3. Get told when it's worth it (optional).** Say *"Check Top Mode every 4 hours
with your cheapest model and only tell me when there is something."* The agent
schedules a quiet check with its own scheduler. It speaks up only when there is
spare capacity to use.

**4. Use it.** From then on, short sentences are enough:

| You say | What happens |
| --- | --- |
| "Is it worth running Top Mode now?" | It checks your quota and says yes, no or unknown, and why. |
| "Start Top Mode for 2 hours." | It picks the most valuable ready work from your setup and gets going. |
| "Status." | What is done and checked, what is in progress, blockers, time left. |
| "Stop Top Mode." | No new work; running tasks save a checkpoint; you get the report. |
| "Explain the report." | Before, after, pending and next step, per project. |
| "Is my plan enough?" | From your Codex quota history: enough, short, enough only thanks to resets, or a cheaper plan would do; how the other plans compare and any coming change to yours. |

## When is it worth it?

| Signal | Codex | Claude Code |
| --- | --- | --- |
| Weekly allowance renews soon and plenty is unused | Yes, from Codex's local logs | Yes, if you let the agent save your status line ([how](references/profile-contract.md#quota-readings)); otherwise it asks you |
| Saved resets are about to expire | Only from Codex's own usage payload, saved and passed to the check ([how](references/profile-contract.md#proactive-check)); local logs don't list them | Not applicable |
| A usage reset is announced | Optional, experimental ([details](references/announcements.md)) | Not applicable |
| You simply want to push work forward | Yes | Yes |

The check only suggests. Top Mode only starts when you say so.

## You stay in control

- **Nothing runs without your approval.** Examples and news never count as permission.
- **Every action has a rule:** `allowed`, `ask` or `deny`. Editing, opening a pull
  request, reviewing and merging are separate; installing, access to accounts,
  money and deleting things are denied or asked by default.
- **Fixed deadline.** It stops at the time limit, if you revoke permission, or
  (when the agent can see your quota) when your weekly allowance renews.
- **One coordinator.** One conversation keeps track of everything. It reuses
  sessions that already own a task instead of piling up new ones.
- **Saved resets are never spent for you.** Each one needs your confirmation.
- **Your setup stays private.** It lives outside Git; updating this package keeps it.

## What a report looks like

> **Notes app.** Before: the import could duplicate entries. After: fixed, tested
> and merged. Pending: release (needs your OK). Next: you approve the release.
>
> **Run:** 1 h 52 min of 2 h, stopped at the deadline. Weekly quota 38% → 71%.
> Tokens: 4.1 M on the strong model, 0.6 M on the cheap one, across 3 sessions.

Full example: [examples/report.example.md](examples/report.example.md).

## What's inside

| File | What it is for |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Entry point for agents. |
| [SKILL.md](SKILL.md) | How the agent sets up, runs, stops and reports. |
| [references/profile-contract.md](references/profile-contract.md) | The setup file, quota sources and report rules. |
| [references/announcements.md](references/announcements.md) | Optional: watching for announced Codex resets. |
| [scripts/install.py](scripts/install.py) | Makes Top Mode available in Codex and Claude Code. |
| [scripts/check.py](scripts/check.py) | The quiet check: speaks only when there is capacity worth using. |
| [scripts/usage_report.py](scripts/usage_report.py) | Quota details, tokens per model and plan history from local logs. |
| [scripts/plan_fit.py](scripts/plan_fit.py) | Rebuilds weekly windows from quota readings, judges the plan and compares the others. |
| [references/plans.json](references/plans.json) | Codex plan prices and sizes, with sources and the date they were checked. |
| [scripts/profile_binding.py](scripts/profile_binding.py) | Remembers where your private setup lives. |
| [scripts/usage_monitor.py](scripts/usage_monitor.py) | Watches Codex quota during a run and decides when to stop. |
| [scripts/capacity_policy.py](scripts/capacity_policy.py) | Checks your setup: is it valid, what is ready, what an action needs. |
| [scripts/public_watch.py](scripts/public_watch.py) | Optional: watches for announced Codex resets and only tells you. |
| [examples/](examples/) | Fictional setup, watch and report examples. |

## Limits

- Needs Python 3.9 or newer (the one that comes with macOS works) and an agent
  that can run commands on your machine.
  Everything runs locally; there is no service, account or dashboard.
- The agent only works while your machine and agent are running. A closed laptop
  doesn't watch anything.
- Token counts come from local logs on this machine. Work done elsewhere isn't counted.
- Quota is shared by everything on your account, so before/after numbers include
  any other work you did meanwhile. The report says so.
- Plan advice covers Codex only for now, and counts Top Mode runs as your own use
  until runs are recorded. Providers publish no exact limits: plans are compared
  by the multiples of Plus that OpenAI has announced, never in tokens. Prices
  and sizes change; the file says when they were checked.
- These are instructions for an agent, not a sandbox. Your agent's own permission
  settings still apply.

Contributing: start with the [vision and principles](references/vision.md), then
the [maintenance guide](references/maintaining.md) and the [changelog](CHANGELOG.md).

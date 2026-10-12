# Top Mode

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

**1. Give your agent this repository** (its URL or a local copy) and paste:

```text
Read the README, AGENTS.md and SKILL.md of this repository.
Tell me what you loaded and what you can do on this machine.
Then help me set up Top Mode: ask me about my projects and priorities,
what to leave out, what you may do without asking, and a default time limit.
Show me the setup in plain words and wait for my approval.
```

**2. Approve the setup.** The agent writes it to a private file outside any Git
repository and remembers where it is. You never need to edit JSON.

**3. Use it.** From then on, short sentences are enough:

| You say | What happens |
| --- | --- |
| "Is it worth running Top Mode now?" | It checks your quota and says yes, no or unknown, and why. |
| "Start Top Mode for 2 hours." | It picks the most valuable ready work from your setup and gets going. |
| "Status." | What is done and checked, what is in progress, blockers, time left. |
| "Stop Top Mode." | No new work; running tasks save a checkpoint; you get the report. |
| "Explain the report." | Before, after, pending and next step, per project. |

## When is it worth it?

| Signal | Codex | Claude Code |
| --- | --- | --- |
| Weekly allowance renews soon and plenty is unused | Yes, from Codex's local logs | Yes, if you let the agent save your status line ([how](references/profile-contract.md#quota-readings)); otherwise it asks you |
| Saved resets are about to expire | Yes, when the Codex app exposes them | Not applicable |
| A usage reset is announced | Optional, experimental ([details](references/announcements.md)) | Not applicable |
| You simply want to push work forward | Yes | Yes |

The check is a suggestion. Top Mode only starts when you say so, unless you
explicitly turned on automatic starts for announced resets.

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
| [scripts/usage_report.py](scripts/usage_report.py) | Quota suggestion and tokens per model from local logs. |
| [scripts/profile_binding.py](scripts/profile_binding.py) | Remembers where your private setup lives. |
| [scripts/usage_monitor.py](scripts/usage_monitor.py) | Watches Codex quota during a run and decides when to stop. |
| [scripts/capacity_policy.py](scripts/capacity_policy.py), [scripts/public_watch.py](scripts/public_watch.py) | Optional announcement watch and conditional start. |
| [examples/](examples/) | Fictional setup, watch and report examples. |

## Limits

- Needs Python 3.11 or newer and an agent that can run commands on your machine.
  Everything runs locally; there is no service, account or dashboard.
- The agent only works while your machine and agent are running. A closed laptop
  doesn't watch anything.
- Token counts come from local logs on this machine. Work done elsewhere isn't counted.
- Quota is shared by everything on your account, so before/after numbers include
  any other work you did meanwhile. The report says so.
- These are instructions for an agent, not a sandbox. Your agent's own permission
  settings still apply.

Contributing: start with the [vision and principles](references/vision.md), then
the [maintenance guide](references/maintaining.md) and the [changelog](CHANGELOG.md).

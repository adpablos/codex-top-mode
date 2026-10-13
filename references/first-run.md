# Your first useful run

Start with one repository you know, one agent and one small task. Keep the
machine awake and the agent open. A 15-minute limit bounds new assignments;
work already running still needs to save its result before the report closes.

## Set up and check

After [installing](../README.md#get-started), open a new agent session in that
repository and say:

> Help me try Quota Coach on this repository only, using this agent without
> delegation. Propose one small pending task with a result we can verify in
> 15 minutes. Use careful permissions, and show me the setup before saving it.

The agent should tell you which installed copy it loaded and its Git revision,
propose a task from your existing work, and explain any permission prompts you
can expect. Approve the specific setup when it fits. If you already have a
setup, narrow this run to this repository without replacing the saved setup.

CodexBar is optional. Without it, Codex can use its local quota logs and Claude
quota stays unknown. A clock-only trial is still useful; its report must say
what could not be measured. Installation and account access keep their own
approval prompts.

## Start, interrupt and finish

When the setup and task are clear, say:

> Start Top Mode for 15 minutes on that task only. Use this agent without
> delegation. Tell me as soon as you need a decision, and finish with a report.

Ask **Status** during the run. It should name the task, its progress, any
decision waiting on you and the original deadline. You can say **Stop Top Mode**
at any time. After a session interruption, ask for status before continuing;
the deadline must remain the same.

At the end, check the result yourself: a changed file, passing test or verified
diagnosis, with its evidence. The report should distinguish attempted work from
finished work and say what remains. Stopping early because no useful work is
ready is a valid outcome. Decide whether the result saved you effort.

## Help test it with a few people

For an initial pilot, use the same published commit with 3–5 volunteers, covering
both Codex and Claude Code. Each chooses their own repository and task and
approves their own setup. First try installation and one task; on a later
session, check updating and whether they want to use it again.

Keep a short note per volunteer, identified by a label they choose:

| Record | What to write |
| --- | --- |
| Environment | OS, agent and Quota Coach revision; CodexBar present or absent |
| Getting started | Minutes from installation to approved task; help needed |
| Interruptions | Number and reason; expected decision or unexpected friction |
| Result | Verifiable outcome, or blocker; useful to the volunteer? |
| Stop and report | Original deadline respected; report matches the result |
| Repeat use | Would they run it again; did they actually return later? |

Collect feedback voluntarily, without telemetry. Keep profiles, local paths,
account details, transcripts and raw reports private. Share only a sanitized
description of a problem with the maintainer, after the volunteer approves it.
Agree how to exchange feedback before inviting anyone.

Prioritize any lost work, unauthorized action or broken stop first. Then fix
repeated installation and permission friction. Broader distribution is ready
for consideration when volunteers can install, complete a useful task and
understand its report without the maintainer guiding each step. Automated
checks establish mechanics; these observations establish usefulness.

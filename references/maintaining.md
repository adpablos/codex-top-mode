# Maintaining Quota Coach

This guide is for changing the package. To use it for your own work, start
with the [README](../README.md) and [agent entry point](../AGENTS.md).

Every change should fit the [vision and principles](vision.md).
Keep changes focused and preserve the [skill](../SKILL.md) and
[profile, quota and report contract](profile-contract.md) as the operating
sources.
Keep review, merge, release and deployment authority separate.

## Optional maintainer review

The [Claude workflow](../.github/workflows/claude.yml) reviews maintenance PRs for
this repository. It is not a requirement for installing or using Quota Coach.
Claude can only read files; it cannot run PR code, edit files or write to GitHub.
Trusted workflow code checks the PR and publishes the result.

A maintainer using this integration needs a personal Claude subscription
credential. Use Anthropic's [official token setup](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token),
then have the human owner enter, confirm and submit it directly in the repository's
**Settings → Secrets and variables → Actions** form, named
`CLAUDE_CODE_OAUTH_TOKEN`. Never put the value in a chat, issue, source file or
commit, and never extract an existing credential store. An agent must hand this
credential-entry step to the human.

Only the repository owner may dispatch or rerun it, from the default branch
(`main` here). First verify the PR is open, ready for review and non-draft, its
checks pass, and its head is the exact full 40-character SHA you intend to review.
Replace both placeholders below:

```sh
gh workflow run .github/workflows/claude.yml --repo adpablos/quota-coach --ref main \
  -f pr_number=PR_NUMBER -f head_sha=FULL_HEAD_SHA
```

Use repository **Actions → Claude final review** to find that dispatch. Accept
a review only when its run succeeds and `github-actions[bot]` publishes a
**Claude final review** comment whose `Reviewed head:` is the PR's current head
and whose verdict is `ready to merge`. A new push invalidates the verdict.
Merge remains a separate authorized action; the workflow never auto-merges.
For `changes required`, fix the material findings together and dispatch again
for the new head. Diagnose failed runs before retrying.

## Contributing and security

### Installation and pilot checks

Keep installation diagnostics in `scripts/install.py`. Its `--check` is local
and read-only; `--update` fetches only the recognized repository's `main`,
refuses dirty or locally committed checkouts and reruns the updated installer.
Do not add another updater or version registry. Git revisions identify snapshots;
an exact release tag identifies a published version when one exists.

The offline suite includes temporary-repository update tests and a first-run
check through installed skill links, from a different working folder and across
separate processes. It covers private setup recovery, unknown quota, a task,
stop, completion checkpoints, report, and uninstall without losing private
state. Deadline enforcement is exercised with a controlled clock. These checks
use synthetic data and no provider calls; they do not prove host permission
prompts, model behavior or account integrations work in a live session.

Use the [first-run guide](first-run.md) for a 3–5-person pilot. Prepare a reviewed
candidate and record its exact commit; invitations, shared feedback and release
publication require the appropriate human authorization. Keep observations
private and bring only sanitized, reproducible problems into the repository.

Before an authorized release, require the checks on the exact commit, a clean
independent review and a completed manual first run in each supported agent.
Record known limits in the release notes, align the version in `pyproject.toml`,
and tag that same commit. Verify that installing and updating reach the
documented revision. Do not label a development snapshot stable based on CI
alone. Start with GitHub distribution; another package channel should solve a
measured installation problem from the pilot.

### Contributor checks

Record user-visible package changes in the [changelog](../CHANGELOG.md). Keep real
run reports and metrics in private storage.

Keep changes small. From the package root, run the same checks as CI. They are
offline, use synthetic fixtures and make no model or account calls:

```sh
python3 -B -m unittest discover -s scripts      # tests, including docs links
ruff check scripts && ruff format --check scripts
python3 -m coverage run -m unittest discover -s scripts && python3 -m coverage report
zizmor --offline .github                        # workflow security audit
```

The runtime has no dependencies and supports Python 3.9+ (the version macOS
ships). `ruff` and `coverage` are only for contributors; their settings live in
[pyproject.toml](../pyproject.toml). [GitHub Actions](../.github/workflows/tests.yml)
runs lint, format and a workflow audit, the tests with an 85% coverage floor on
Python 3.13, and the tests on macOS's own Python (3.9; the job fails if the
runner ships another version), with pinned actions and read-only permissions. Its `all checks` job fails when any of them fails; it is
the one check to require before merging. Dependabot proposes action updates
after a 7-day cooldown.
Preserve authorization, fixed deadlines, deduplication,
coverage honesty and private storage. Do not include keys, cookies, account IDs, real profiles or
private conversations in fixtures, issues or patches. Do not publish sensitive
reports as issues: use a maintainer's private contact if available, otherwise
request one without disclosing the material. No private reporting endpoint is
claimed before publication.

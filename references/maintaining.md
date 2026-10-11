# Maintaining Top Mode

This guide is for changing the package. To use it for your own work, start
with the [README](../README.md) and [agent entry point](../AGENTS.md).

Every change should fit the [vision and principles](vision.md).
Keep changes focused and preserve the [skill](../SKILL.md) and
[profile, quota and report contract](profile-contract.md) as the operating
sources; the optional announcement watch lives in [announcements](announcements.md).
Keep review, merge, release and deployment authority separate.

## Optional maintainer review

The [Claude workflow](../.github/workflows/claude.yml) reviews maintenance PRs for
this repository. It is not a requirement for installing or using Top Mode.
The model reads frozen PR files; it cannot execute PR code, edit files or write
to GitHub. Trusted workflow code verifies and publishes its result.

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
Replace both placeholders below; leave the default economical runner unchanged:

```sh
gh workflow run .github/workflows/claude.yml --repo adpablos/top-mode --ref main \
  -f pr_number=PR_NUMBER -f head_sha=FULL_HEAD_SHA
```

Use repository **Actions → Claude final review** to find that dispatch. Accept
a review only when its run succeeds and `github-actions[bot]` publishes a
**Claude final review** comment for the exact current head, base head and merge
base, with complete coverage and `Verdict: ready to merge`. The Actions run's
own head is the default-branch workflow revision, not the PR head. Check the
comment's frozen identity against the live PR; movement invalidates the verdict.
Merge remains a separate authorized action; the workflow never auto-merges.

For `changes required`, fix the material findings together and request closure
review of the new frozen identity. Do not run a parallel Cloud or `@claude`
review of the same candidate. Diagnose failed runs before retrying. A standard
runner recovery needs verified economy watchdog-timeout evidence and its
`fallback_run_id`; authentication, setup failure or cancellation does not qualify.
After ten completed published passes, continuation needs a diagnosed, explicit
per-pass human decision with an unused `extra_pass_authorization` reference.
Read the workflow's input and refusal rules rather than inventing authority.

## Contributing and security

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
coverage honesty, private storage and legacy observer behavior. Use supported
public HTTP only. Do not include keys, cookies, account IDs, real profiles or
private conversations in fixtures, issues or patches. Do not publish sensitive
reports as issues: use a maintainer's private contact if available, otherwise
request one without disclosing the material. No private reporting endpoint is
claimed before publication.

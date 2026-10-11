# Maintaining Codex Top Mode

This guide is for changing the package. To use it for your own work, start
with the [README](../README.md) and [agent entry point](../AGENTS.md).

Keep changes focused and preserve the [skill](../SKILL.md) and
[profile/event contract](profile-contract.md) as the operating sources.
Keep review, merge, release and deployment authority separate.

## Optional maintainer review

The [Claude workflow](../.github/workflows/claude.yml) reviews maintenance PRs for
this repository. It is not a requirement for installing or using Top Mode.
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
gh workflow run .github/workflows/claude.yml --repo adpablos/codex-top-mode --ref main \
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

Record user-visible package changes in the [changelog](../CHANGELOG.md). Keep real
run reports and metrics in private storage.

Keep changes small; run the offline suite with synthetic fixtures and no real
model/account calls:

```sh
python3.13 -B -m unittest discover -s scripts -v
```

Run it from the package root. Python 3.11+ is the runtime minimum; CI uses
Python 3.13. [GitHub Actions](../.github/workflows/tests.yml) runs the same
offline suite on pull requests and pushes to `main`, with Python 3.13, pinned
official actions and read-only permissions. Verify the **Offline tests** run
and its test count. Tests need no runtime dependency installation, X/model calls
or repository secrets.
Preserve authorization, fixed deadlines, deduplication,
coverage honesty, private storage and legacy observer behavior. Use supported
public HTTP only. Do not include keys, cookies, account IDs, real profiles or
private conversations in fixtures, issues or patches. Do not publish sensitive
reports as issues: use a maintainer's private contact if available, otherwise
request one without disclosing the material. No private reporting endpoint is
claimed before publication.

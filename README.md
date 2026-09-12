# sourcerepo

Central automation hub for all personal GitHub repositories. Every owned, non-disabled repo gets configuration, workflows, and hygiene rules synced from here on a weekly cadence.

## How it works

**Single workflow, weekly cron, cascade-safe.**

| Workflow | Purpose | Trigger |
|----------|---------|---------|
| `sync-repo-settings.yml` | Repo settings + secrets + config files across all repos | Weekly Mon 5pm SGT + manual dispatch |

Underlying script: [`.github/scripts/sync-selected-paths.sh`](.github/scripts/sync-selected-paths.sh)

### Why weekly and not hourly?

Previously ran every 3 hours across 3 workflows → hit spending limit repeatedly. The cost-optimised weekly schedule + `[skip ci]` on downstream commits (to prevent fan-out cascade) cut Actions usage by an estimated 60–75%.

### Cascade prevention

The sync script commits config files to every target repo with `chore(config): sync from sourcerepo [skip ci]`. The `[skip ci]` marker tells GitHub Actions to skip triggering downstream workflows (CI, CodeQL, Scorecard, etc) in each target repo. Without this, one sync run would fan out to trigger 90+ repos × N workflows = quota-exhausting.

### Application file preservation

Config sync updates the configured shared paths. It preserves downstream
documentation, skills, dot directories, editor workspaces and other unlisted
application files. Shared template directories are merged so custom forms remain.
Linked destinations and file/directory conflicts stop that repository's update
without publishing a partial copy.

Repository enumeration must succeed before work starts. Topic lookup failures
skip the affected repository and make the job fail; `no-config-sync` is checked
before cloning or changing archive state. Metadata, clone, copy and push failures
return a nonzero status. Existing weekly scheduling and downstream skip-CI commit
messages are unchanged. Files removed by earlier syncs need a separate review of
Git history; this change prevents repeat deletion and does not guess how to restore them.

Run `python -B -m unittest discover -s tests -p test_config_sync.py -v` with
Python 3.12, Bash, Git and jq. The tests use temporary local repositories and a
fake GitHub CLI; they cannot push over network Git transports or change real
repository settings. Linux CI also verifies symlink preservation.

## What gets synced

Every non-disabled repo (**including archived** — see below) receives:

| Item | Source path |
|------|-------------|
| GitHub Actions workflows | `codeql.yml`, `scorecard.yml`, `trufflehog.yml`, `heartbeat.yml`, `lfs-guard.yml`, `dependabot-auto-merge.yml`, `auto-merge-bots.yml`, `dependency-review.yml`, `summary.yml`, `labeler.yml`, `greetings.yml` |
| Bot merge policy | `.github/scripts/checked-bot-merge.py` |
| Dependabot config | `.github/dependabot_config.yml` → `.github/dependabot.yml` |
| Issue + PR templates | `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md` |
| Community files | `CONTRIBUTING.md`, `SECURITY.md`, `AGENTS.md` |
| Config | `.gitattributes`, `.deepsource.toml`, `.sourcery.yml`, `.github/labels.yml`, `.github/greetings.yml`, `.github/FUNDING.yml`, `LICENSE`, `NOTICE` |

**Also propagates:**
- Repo settings (auto-merge, delete-on-merge, discussions, wiki, issues, description, homepage)
- `GH_PAT` secret (for cross-repo automation)

## Archived repos

The sync handles archived repos via **unarchive → sync → re-archive** dance:

1. Detect archived flag via API
2. `PATCH archived=false`
3. Clone, apply changes, push
4. `PATCH archived=true` — restore archived state
5. On failure to re-archive, exit non-zero + surface loudly (so it's fixable)

To skip archived repos on a specific run: manual dispatch with `include_archived=false`.

## Per-repo opt-outs — GitHub Topics

Set a topic on a specific repo to change its sync behavior. Topics survive across sync runs (they're metadata on GitHub's side, not files).

| Topic | Effect |
|---|---|
| `keep-lfs` | Sync **skips** overwriting `.gitattributes` and installing `lfs-guard.yml`. The workflow (if already present) detects the topic at runtime and exits as a no-op. Use when a repo genuinely needs Git LFS. |
| `no-config-sync` | Sync **skips all config file operations** for this repo. Repo still receives settings and secrets from the other jobs but files stay untouched. Use for repos you want to fully control by hand. |

### Setting a topic

Via CLI:
```bash
gh repo edit hongyime/<repo> --add-topic keep-lfs
gh repo edit hongyime/<repo> --add-topic no-config-sync
```

Via UI: repo page → click gear icon next to **About** → Topics field → add → save.

### Removing a topic

```bash
gh repo edit hongyime/<repo> --remove-topic keep-lfs
```

Or via UI, same location.

### Listing topics for all your repos

```bash
gh api "user/repos?per_page=100&affiliation=owner" --paginate \
  --jq '.[] | {name, topics}'
```

## LFS accident prevention

Two layers stop new Git LFS bloat:

1. **`.gitattributes` template** (synced to every repo without `keep-lfs`): explicit `-filter -diff -merge` rules for 20+ common binary patterns (`*.png`, `*.jpg`, `*.mp4`, `*.log`, `*.txt`, `*.zip`, etc). Prevents accidental LFS auto-capture even if a `git lfs track` command is run.

2. **`lfs-guard.yml`** (synced to every repo without `keep-lfs`): CI workflow that scans HEAD for Git LFS pointer files on every push and PR. Fails the check if any exist, with a clear error message and opt-out instructions.

**Why this matters:** the pokemoncards repo hit 11.6 GB LFS = 1187% of free quota, blocking all LFS downloads across ALL repos on the account. Recovery required delete+recreate of the repo (loses stars/issues/PRs/watchers) OR a GitHub Support ticket (3-day wait). The guard makes the accident impossible.

## Bot PR auto-merge

Bot PRs merge automatically. Both workflows use `GH_PAT` with `--admin` to bypass branch protection:

| Bot | Workflow |
|-----|----------|
| Dependabot | `dependabot-auto-merge.yml` |
| Snyk, Sourcery, DeepSource, GitHub Copilot SWE | `auto-merge-bots.yml` |

## Setup (first-time)

1. Create a **classic** GitHub PAT with scopes: `repo`, `workflow`, `admin:repo_hook`, `delete_repo`
2. Add as `GH_PAT` in this repo: Settings → Secrets → Actions
3. Run `sync-repo-settings.yml` manually (workflow_dispatch, include_archived=true) to propagate everything
4. `GH_PAT` is auto-propagated to all other repos on subsequent runs

## Manual operations

Sync now (all repos including archived):
```bash
gh workflow run "Sync Repo Settings & General Config to All Repos" --repo hongyime/sourcerepo -f include_archived=true
```

Merge all open bot PRs across account:
```bash
gh workflow run "Auto-merge Bot PRs" --repo hongyime/sourcerepo
```

## Local sync (X: drive)

The `X:\01 REPOSITORIES` root has small `.bat` wrappers for local workspace
maintenance. They call the tracked Python helpers in `tools/workspace/`.

Install or refresh the root wrappers from this repo:

```powershell
pwsh -File .\tools\workspace\install_root_bats.ps1
```

- `02 RunSync.bat` → runs `tools/workspace/sync_workspace.py`; clones missing
  in-scope repos and fast-forwards clean local branches only.
- `03 RunPush.bat` → runs `tools/workspace/push_workspace.py`; reports clean
  ahead-only repos, then pushes them only after explicit confirmation. It never
  creates commits.
- `06 RunSourceSync.bat` → triggers the GitHub Actions fan-out sync from
  `sourcerepo`.

Both local pull/push helpers are repeatable. Dirty, detached, behind, diverged,
external, or slow repos are reported and skipped rather than overwritten.

## Retry and failure behavior

- Exponential backoff (3 attempts, 2^n s delays) on clone and push
- PR fallback if direct push fails (protected branch): opens `sync-<run-id>` branch + PR
- Clone, push, and re-archive failures collected and reported at end of run
- Re-archive failures exit the script non-zero to surface loudly

## Visibility policy

Visibility is enforced by `sync-repo-settings.yml` from `repos.yml`.

Current practical policy:

- Repos are public by default.
- Set `visibility: private` in `repos.yml` for private operations,
  credentials-adjacent automation, private data workflows, or unclear exposure risk.
- Compliance reports flag visibility drift, and the weekly settings sync enforces
  the configured public/private state.
- Do not restore the old private-except-`theprawn` rule; it does not match the
  current estate.

## Bot merge checks

The shared bot workflows evaluate completed builds and status updates, or an
explicit manual sweep. They read the policy from the trusted default branch and
never check out PR code with the merge token. All paths require an open bot PR in
the same repository, the default target branch, clean mergeability, a required
successful `Build Check` / `Build` result, and no unfinished or failed checks.
The merge request includes the exact checked head SHA. Missing checks, failed API
lookups, draft/fork PRs and changed heads leave the PR open.

Repositories without that required Build check need manual review. Before
re-enabling automation for a Vercel project, its actual deployment check must also
be configured as required and verified on a representative PR. A successful
generic CI job that skips the app build is not sufficient validation. Do not
enable the workflow until the repository's real build is mapped and tested.

Application `ci.yml` is owned by each target repository and is no longer copied
by the shared sync. The source repository's own Build Check runs the merge-policy
regressions. Run `python -m unittest discover -s .github/tests -v` locally.

The September 12 portfolio rollout suspends the confirmed unsafe legacy bot
merge workflows while each repository's requirements are validated. Build,
security and deployment workflows continue. Updating a workflow's file does not
constitute verification or authorization to re-enable it automatically.

## Files preserved during sync

- Preserve unlisted dot items, editor workspaces, skills and documentation.
- Merge shared template directories while preserving custom forms.
- Maintain the marked `.gitignore` block without deleting application files.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.

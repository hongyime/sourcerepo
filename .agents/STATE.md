# Config-sync preservation — 2026-09-10

The preservation fix is implemented on `maintenance/config-preservation-20260910`, based on published helper release `22d2798`. Source review found broad downstream deletion of documentation, skills, dot directories and editor workspaces; replacement of shared template directories also removed custom files. Topic API errors previously bypassed opt-outs.

Config sync now preserves unlisted app files, merges managed directories, refuses linked/type-conflicting destinations, checks metadata before cloning or changing archive state, and reports partial failures through a nonzero exit status. All eleven fixture checks passed in Linux CI for code commit `c510115`: https://github.com/hongyime/sourcerepo/actions/runs/34453272672. Tests use temporary local Git repositories and a fake GitHub CLI with network Git transports disabled. The local Windows attempt failed during Git Bash process creation before tests ran; local WSL startup also failed. Those are environment limitations, not baseline application-test results.

The weekly schedule and downstream skip-CI messages are retained. No organization-wide workflow was dispatched, so its next live scheduled execution remains unverified. Existing workspace edits remain separate. Historical app files removed by earlier syncs require per-repository Git-history review; this fix prevents repeat deletion but does not restore unknown historical content.

# Workspace sync maintenance — 2026-09-10

Safe mode now prints discovery and per-repository progress, distinguishes Git failures from dirty/detached branches, and returns failure status when commands fail. Windows timeouts terminate the launched process tree so portable Git children cannot hold output pipes open. Local metadata/status checks default to 30 seconds. Eleven regression checks cover timeout behavior, failed checks, empty repositories and safe fast-forward decisions. Automatic object repacking is deferred during both bulk fetch and fast-forward commands, without changing persistent Git settings. Existing local clone-layout work is excluded from this release.

Previous handoff follows.

# STATE

**Updated:** 2026-08-09 SGT
**By:** codex / machine: desktop
**Branch:** `molt/state-continuity`
**Ended because:** ready for cross-harness proof with committed handoff

---

## Task

Establish MOLT Layer 0 so work can resume across harnesses using committed
plain-text state instead of private session stores.

## Status

`ready-for-review`

## Done so far

- Added `.agents` preservation to the central sync cleanup.
- Kept `.claude/` local-only and ignored.
- Updated `AGENTS.md` to require reading `.agents/STATE.md` first.
- Removed stale `sync-skills.yml`, `sync-mcp.yml`, and `.claude/skills/`
  references from `AGENTS.md`.
- Added thin pointer files for Claude, Gemini, and Kiro.
- Seeded `theprawnprojects/.agents/STATE.md` as the first active repo state
  file.
- Repointed local `session-handoff` skill copies from `.claude/handoffs/` to
  `.agents/handoffs/` and made validation block on secret or identity hits.
- Added a committed handoff document under `.agents/handoffs/` so a cold
  harness has a compact resume target in addition to this state file.

## Next steps

1. Prove resume behavior from a different harness by asking it to read
   `X:\01 REPOSITORIES\_shell\PROGRESS.md`.
2. Ask that harness to also read the latest handoff in `.agents/handoffs/`.
3. If the harness picks up the current state, push/open PRs for the MOLT
   branches.
4. Keep SHELL remediation paused until central sync/state changes are reviewed.

Exact Phase 3 proof prompt to paste into a different CLI:

```text
resume from X:\01 REPOSITORIES\_shell\PROGRESS.md
```

## Decisions made

- Track only `.agents/STATE.md`, `.agents/JOURNAL.md`, and
  `.agents/handoffs/**`; keep `.agents/skills/` ignored to avoid committing a
  large generated skills tree.
- Use `The Prawn Organisation` for organization-facing copyright text.

## Gotchas

- Windows/PowerShell environment; bash has fork issues on this machine.
- Do not put secrets or personal details in `.agents/`.
- Do not rely on `.claude/` for cross-harness state.
- `_shell/PROGRESS.md` is outside a Git repo on this machine; it cannot be
  committed unless `_shell` becomes a repo or the file is copied into a repo.
- `sourcerepo` still has uncommitted SHELL scaffold/audit files from the Claude
  SHELL run. They are separate from the MOLT commit.
- Local Git config previously had credential-bearing remote URL entries; they
  were removed, leaving only `remote.origin.url`.

## Files in play

- `AGENTS.md`
- `.gitignore`
- `.github/scripts/sync-selected-paths.sh`
- `.agents/STATE.md`
- `.agents/JOURNAL.md`
- `.agents/handoffs/`
- `.agents/handoffs/2026-08-09-molt-layer0-ready.md`
- `X:\01 REPOSITORIES\theprawnprojects\.agents\STATE.md`
- `X:\01 REPOSITORIES\_shell\PROGRESS.md`

## Open questions for the human

- Which alternate harness should perform the proof: Gemini, Claude, Kiro, or
  another installed CLI?


## 2026-09-12 — checked bot merges

Accepted portfolio upkeep: fix the verified early dependency merge and admin bypass. Preserve the original workspace edits.

- [x] Recheck all 27 Vercel projects and preserve unrelated local work.
- [ ] Verify default-branch bot workflows across the 81-repository inventory; suspend confirmed unsafe active merge workflows without affecting build or deployment workflows.
- [x] Replace shared early/admin paths with one tested policy requiring nonempty required checks and a successful Build check for the current PR head; use ordinary SHA-guarded merging.
- [ ] Publish the shared repair, verify hosted checks, and validate affected repository policies before re-enabling their automation.
- [ ] Refresh public sites and publish the HTML/Markdown report with remaining rollout and free-tier limits.

Local validation: 16 merge-policy/CI-ownership regression tests pass. Four changed workflow files parse. No application files or production data were changed. Downstream workflow activation remains pending repository-specific validation.


2026-09-12 heartbeat/build-protection follow-up: inspect actual scheduled workflows before replacing direct heartbeat commits. Preserve manually disabled jobs and all existing collector behavior; never resume private/scanning services as a side effect.
- [ ] Trace current heartbeat and shared sync behavior; identify repositories whose scheduled work is limited to repository maintenance.
- [ ] Prove deployment waste from heartbeat commits and define a replacement without silently resuming collectors or manually disabled jobs.
- [ ] Implement and test a bounded repair; preserve local edits, action restrictions and data collection behavior.
- [ ] Release the shared repair and verify affected repository and production state.
- [ ] Update the portfolio Markdown and HTML with measured progress and remaining limits.

2026-09-12 heartbeat validation passed locally. Source policy tests and workflow parsing pass; the application pilot builds pass. Hosted PR checks, production matching and the first branch heartbeat are the next release gates. No broad sync or disabled workflow reactivation was run.

2026-09-12 required-check rollout: the previous heartbeat pilot is released and verified. This pass repairs protected-branch config sync before enforcing Build and Vercel checks on Prawn Game and Prawn Surprise. Task list: verify current rules/check identities; consolidate real app validation under an always-scheduled Build; prove protected config PRs and error handling in local Git fixtures; release the shared and app repairs; verify required checks, safe bot policy and heartbeat compatibility; update the portfolio report. The shared script now reads branch protection before any clone/archive change, sends protected changes directly to PRs without skip directives, and reports PR-creation failures. The existing 25 maintenance-policy tests pass; the extended Git fixture suite, hosted checks and publication remain pending. No live broad sync or workflow reactivation has run.

2026-09-12 local verification: shell syntax and all 25 shared policy tests pass; the updated bot workflows also re-evaluate after GitHub default CodeQL completes. The extended Git fixture run could not validate behavior on this Windows host: Bash child_copy/dofork resource failures prevented command execution, including unchanged preservation cases. The 18-case fixture suite must pass on the hosted Linux runner before this source repair is merged. No live config sync has been dispatched.

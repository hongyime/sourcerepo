# JOURNAL

- 2026-08-09: Chose committed `.agents/STATE.md` plus `.agents/handoffs/` for
  cross-harness state because private harness stores do not survive tool
  switches or machine switches.
- 2026-08-09: Kept `.agents/skills/` ignored because MOLT needs durable state,
  not a large generated skills mirror committed into every repo.
- 2026-08-09: Added a committed MOLT handoff under `.agents/handoffs/` so
  future harnesses can resume from either `_shell/PROGRESS.md` or the repo-local
  handoff.

- 2026-09-10: Fixed workspace sync progress, failure classification and Windows child-process timeouts; use 30-second local-check defaults. Keep safe mode limited to clean fast-forwards and preserve unrelated local clone-layout work.

- 2026-09-10: Prioritized config-sync preservation after source review found deletion of app-owned files and opt-outs bypassed on metadata errors. Validate with temporary repositories before publishing; retain the weekly schedule and skip-CI downstream commits.

- 2026-09-10: Linux CI run 34453272672 passed all eleven config-sync fixture checks, including file preservation, failed metadata, opt-outs, copy conflicts and archive restoration. Local Windows/WSL attempts were environment failures; no live organization sync was run.


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

2026-09-12: Required-check rollout preserves direct skip-CI updates only for unprotected branches; protected branches and rejected direct pushes use review commits with runnable checks. Unknown protection and failed PR creation fail visibly. Preserve all existing app data and workflow pauses until live gates are verified.

2026-09-12 local verification: shell syntax and all 25 shared policy tests pass; the updated bot workflows also re-evaluate after GitHub default CodeQL completes. The extended Git fixture run could not validate behavior on this Windows host: Bash child_copy/dofork resource failures prevented command execution, including unchanged preservation cases. The 18-case fixture suite must pass on the hosted Linux runner before this source repair is merged. No live config sync has been dispatched.

2026-09-12 LFS checkout/capacity rotation: the current-index guard needs no history. Use depth 1 while preserving the opt-out, scan pattern and existing action references; scan errors now fail instead of becoming a false no-pointer success. Ten local fixture cases compare shallow/full clones and exercise current, historical, nested/spaced and merge-commit pointers. Seven pass on Windows; three exact Bash cases must pass on hosted Linux before release. The synthetic removed-blob fixture measures 2,099,719 bytes of full-clone objects versus 1,499 shallow bytes with equal index results. All 25 existing shared-policy tests pass. New fixture CI is source-only and is not in the downstream sync list. A source merge does not trigger broad settings sync. Next: require all 10 hosted fixtures and security checks, release the source, then a bounded three-repository pilot while preserving all local edits and workflow states. Supabase aggregate follow-up and an independent synthetic-only PostgreSQL runtime are separate capacity work; no shared Docker, collector or database mutation.

2026-09-12 nested heartbeat preparation: SMU Courses uses Vercel root web, so extend the shared opt-in to one validated plain directory. Owned heartbeat trees include both root and nested disabled-deployment configs and record the root in the ownership marker. Root-app markers/history remain byte compatible. Unexpected files, modes, changed roots, traversal and concurrent ref updates fail without overwriting history. All 29 shared policy tests pass locally; hosted policy and config preservation checks must pass before source release. Rollout is bounded to Swiperboxd and SMU Courses; no broad sync or provider data workflow is dispatched.

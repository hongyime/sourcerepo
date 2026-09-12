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

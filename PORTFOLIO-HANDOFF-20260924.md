# Portfolio Cross-Pollination — Handoff / Resume State

**Last session:** opencode/Sisyphus, ended 2026-09-24 (paused by user request, not finished — most work IS done, a handful of items are genuinely blocked on human/manual action).

**If you are a fresh agent or machine picking this up: read this whole file first.
GitHub is the source of truth — do NOT trust the X-drive mirror
(`\\100.92.164.125\x-drive\01 REPOSITORIES`) as current; other machines/agents
edit it concurrently and it can be stale. Use `gh` CLI / GitHub API to verify
real state before acting.**

## Scope & ground rules

- In scope: repos owned by `hongyime` and `bryanseah234` only.
- Out of scope (do not touch): repos owned by bchuminx, decker757, jininggg,
  Joe-Zhou-Yubin, keene-ng-2024, yinasaurus — collaborator/push access does not
  make these in-scope.
- No PR review required for this portfolio; pushing straight to `main` is fine
  *except* on branch-protected repos (e.g. `smucourses`) — open a PR there instead.
  Merge everything mergeable; leave anything genuinely requiring human review alone.
  Keep open-PR count trending to 0.
- Every repo should have `CONTRIBUTING.md` + `SECURITY.md`.
  Free tier only (Vercel/Supabase/GitHub Actions). Keep deploys fast.
  `sourcerepo` (this repo) is the shared template/source-of-truth and is
  editable directly.
- Per-repo state tracking uses the MOLT pattern: **each repo gets its own**
  `.agents/STATE.md` (current snapshot, overwritten) and `.agents/JOURNAL.md`
  (append-only dated decisions) — not a single root-level file.
- Always `git pull`/fetch latest before editing a repo. Push/commit immediately
  per change, don't batch multiple repos' work into one uncommitted pile.
- New Supabase tables in the `public` schema need **explicit GRANTs**
  (`GRANT SELECT, INSERT, DELETE ON ... TO anon, authenticated, service_role`
  + sequence grants) — Supabase is removing the auto-grant for new tables
  around Oct 30; existing tables are unaffected.

## Known environment gremlins (don't waste time rediscovering these)

- The SMB mount (`\\100.92.164.125\x-drive\...`) has severe intermittent
  latency: `git status/fetch/pull`, recursive directory listing, and
  `npm test`/`node --test` routinely hang 20s-60s+ for no functional reason.
  Non-recursive listing works fine. **When git/npm hangs, fall back to the
  GitHub Contents API** (`gh api repos/OWNER/REPO/contents/PATH -X PUT` with
  base64 content + current `sha`) to read/write files directly — much more
  reliable than the mounted drive.
- Many repos' CI (`ci.yml` / "Build" check) triggers on `pull_request` only,
  **not** `push` and has no `workflow_dispatch`. To get a real CI signal for
  something already pushed straight to `main`, open a *throwaway* branch+PR
  (trivial comment-only diff is enough to satisfy path filters), read
  `GET /repos/{repo}/commits/{branch}/check-runs`, then close the PR without
  merging and delete the branch once green.
- `team_mode`/`team_*` tools were unreliable all session (lock timeouts,
  "session lineage" spawn-block errors) — plain `task()` delegation, launched
  one at a time (not in large parallel batches), worked better.
- Background task "Aborted"/"completed" status labels are **not trustworthy**
  — sessions have kept working for hours after being reported finished.
  Verify via `session_info`/`session_read` before treating a task as done.

## Overall status (waves 1-12 + ad hoc)

All of the following are **done and verified** (CI green / commits confirmed
on `main` via `gh api`, not just locally):

- CI fixes: `ctfsolver`, `FORGE`, `gmaplists` (SHA-pinning + new keepalive workflow).
- Supabase keepalive: `sgBusLaoBu2021` fully done (table+GRANTs+secrets verified).
  `sgConnectSphere2026` table+secrets done (PR blocked — see below).
  `theprawnhunter` blocked — see below.
- SHELL baseline docs/workflows synced to 7 repos (ctfsolver, emailverification,
  networkScan2020, playchess, trexrunner, youtubepublisher, sgCampusCore2026).
- PR sweep: 90 PRs merged across the portfolio in total.
- Branch cleanup/standardization to `main`: playchess, pythoncrash, rainbowchess,
  searchIG2020, sgCarParks2020 (rainbowchess also had 8 stale branches removed).
- Vercel hardening: `spritescavenger`, `theprawnhunter` fixed directly;
  `smucourses` PR #31 opened (branch protected — confirm merge status).
- Untracked-file sweep: 20-repo pre-scoped list, all clean.
- `.agents/STATE.md` + `JOURNAL.md` added to: sgCertWatch2026, sgNRIC2003,
  sgNRICgenerator65, sgNumbers2020, sgPhoneNumbers65, websiteDOS2019,
  theprawnsplit, **sgCampusCore2026** (just added this session).
- Labeler workflow bug (wrong config path + missing `permissions:`) fixed
  across 5 repos, unblocking 9 previously-stuck PRs.
- `sgCertWatch2026` security regression (XSS-class URL sanitization bypass in
  `lib/ui/evidence-timeline.js`) fixed forward per user's explicit approval
  (commit `5dbf7483`); PR #19 merged.
- Hardening sweep: GitHub Dependency Graph enabled on `sgConnectSphere2026` and
  `supabasealive` (2 of 69 checked, were disabled). Sampled 12 repos for
  unpinned Action refs (tag instead of SHA) — **widespread finding, not yet
  remediated portfolio-wide**, see below.
- Test-writing on 5 flagged production repos:
  - `ticketremaster-b` — done. Found 12/13 services already had orphaned
    pytest suites never wired into CI (`pytest.ini` pointed at a nonexistent
    root `tests/`); added tests for `notification-service`; added
    `.github/workflows/python-tests.yml`; fixed 2 real bugs found by the new
    CI (missing route decorator in `seat-inventory-service`, field leak in
    `event-service`). All 13 services pass in CI.
  - `sgCertWatch2026` pipeline/backend layer — done, commit `957351e`,
    129 new tests.
  - `dejavista` — done, 94/94 tests pass, new `tests.yml` CI workflow.
  - `sgCampusCore2026` — done this session: 110 new tests (severityFloor,
    category, llmTriage, sla) + fixed a missing `.first()` method in the
    shared `config/testing/convex-fixture.mjs` mock. Verified via throwaway
    PR #61 (closed, not merged) that the real CI Build job is green.
  - `gmaplists` — **not done**, system-cancelled via stale-timeout mid-task.
    See action items below.

## Outstanding action items (what still needs doing, per repo)

1. **`theprawnhunter`** (Supabase) — table creation returned HTTP 400 (cause
   unclear, possibly a conflict with an existing singular `keepalive_log`
   table). No `wrangler` CLI or Cloudflare credentials were available in the
   session environment, so the Worker secret couldn't be set either.
   TODO: create the `keepalive_logs` table manually (check for a naming
   conflict with the existing `keepalive_log` table first), set
   `SUPABASE_URL`/`SUPABASE_ANON_KEY` repo secrets, then update the
   placeholder project ref for theprawnhunter in `supabasealive`'s
   `src/index.ts` PROJECTS array and run
   `wrangler secret put SUPABASE_ANON_THEPRAWNHUNTER` against the
   `supabasealive` Worker.
2. **`sgConnectSphere2026` PR #122** — 2 failing checks (`pr-conventions`,
   `repository-checks`) that don't correspond to any workflow file in the
   repo (likely a GitHub App / branch-protection-injected check).
   TODO: investigate what app/setting owns these checks, or ask the user.
3. **`gmaplists`** — test-writing task was cancelled by the system's
   stale-timeout guard mid-run (no replacement was auto-spawned, per its own
   instruction). Diagnosed as likely a one-off session glitch, not a real
   scoping problem. TODO: decide whether to retry (get explicit go-ahead
   before relaunching — this was flagged to the user and not yet answered
   as of this handoff).
4. **Unpinned GitHub Actions, portfolio-wide** — hardening-sweep sample of
   12 repos found widespread use of tag refs instead of pinned SHAs:
   `theprawnsplit` (~40+ unpinned across 16 workflows), `ticketremaster-f`
   (~35+), plus others. TODO: decide if/when to run a dedicated remediation
   wave (mirroring the SHA-pinning fix already done for `gmaplists`' CodeQL
   workflow and the original Wave 1 CI fixes).
5. **Supabase PAT rotation** — a live personal access token
   (`sbp_cb26...` — see chat history for the full value, not repeating it
   here) was pasted into chat during Wave 2 and used directly (never passed
   into any subagent prompt) to provision Supabase tables/secrets for
   `sgBusLaoBu2021` and `sgConnectSphere2026`. **The user should rotate/revoke
   this token** — not confirmed done as of this handoff.
6. **`smucourses` PR #31** (`.vercelignore` addition, branch protected) —
   opened, merge status not reconfirmed since. TODO: check and merge if green.

## How to resume

1. Re-verify each "done" item above with a live `gh` call before assuming it's
   still true (another machine/agent may have touched these repos since).
2. Work through the 6 outstanding items above — most need either credentials
   the previous session didn't have (Cloudflare/`wrangler`) or a human
   decision (retry gmaplists? run the unpinned-actions wave? rotate the PAT?).
3. Everything else in the original 8-wave cross-pollination plan is complete.
   If picking up fresh context on "what was the plan," the original audit
   that drove it is at
   `audit_results/practices-audit-20260922/batch-{alpha,bravo,charlie,delta}.md`
   on the X-drive (not git-tracked — read-only reference, not a sync target).

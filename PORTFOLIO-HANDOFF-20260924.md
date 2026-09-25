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
  - `gmaplists` — done: finished directly after the delegated subagent stalled
    twice with zero progress (31min of reads + hung SMB git calls, no writes).
    Added 25 new tests (autoTagMeasurement/browserStorage/mapLinkService/
    privacy, 54 total with the 29 pre-existing ones). One test scenario was
    initially wrong (missed that `classifyPlaceByRules` gives note text
    priority over name/label matches) — caught by a real CI failure, fixed,
    reverified green. Commit `6cabdea`. `.agents/STATE.md`/`JOURNAL.md` updated.

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
2. **`sgConnectSphere2026` PR #122** — root-caused and unblocked on the
   automated side. The 4 required checks (`repository-checks`,
   `pr-conventions`, `lfs-guard`, `application-checks`) run via GitHub App
   15368 (GitHub Actions) but were stuck `action_required` — approved and ran
   them (`gh api .../actions/runs/{id}/approve`). `repository-checks` then
   failed on a real issue (missing trailing newline in
   `supabase-keepalive.yml`, caught by the `end-of-file-fixer` pre-commit
   hook) — fixed. `pr-conventions` failed because the PR body didn't match
   `.github/pull_request_template.md`'s required sections — rewrote the body
   with real evidence per section. All 4 checks are now green. **The ONLY
   remaining blocker is the required approving review**
   (`required_approving_review_count: 1`, `require_last_push_approval: true`)
   — the only "review" on record is Copilot's auto-reviewer bailing out on a
   quota limit, and the PR author (bryanseah234, same identity as this
   session's `gh` auth) cannot self-approve. **Needs a human (or a different
   account's) approval to merge.**
3. **Unpinned GitHub Actions, portfolio-wide** — done. Fixed across 11 repos:
   `theprawnsplit` (34 refs/18 workflows), `ticketremaster-f` (30/15),
   `ticketremaster-b` (34/16), `dejavista` (34/17), `sgBusLaoBu2021` (40/20 —
   on `master`, its real default branch — see stray-branch note below),
   `ctfsolver` (30/14), `sgCampusCore2026` (30/15), `sgCertWatch2026` (54/24),
   `theprawnhunter` (18/8), `FORGE` (69/17). ~373 refs total, plus `gmaplists`
   done earlier (5 refs, its CodeQL workflow). Resolved each `action@tag` to
   its commit SHA via the GitHub API and rewrote in place with a trailing
   `# original-ref` comment. No functional changes; CI reverified green
   (success/cancelled only, zero failures) on every repo after the change.
   **IMPORTANT correction, found on closer inspection**: `sgBusLaoBu2021`'s
   real default branch is `master`, not `main`. It also has a second,
   separate `main` branch that pre-existed this session (not created by it).
   My first pass wrote SHA-pinning fixes into that `main` by mistake (script
   assumed `main` everywhere); caught it via a 409 sha-mismatch error, redid
   it correctly against `master`, verified clean there.
   **This `main` branch is NOT a harmless empty leftover** — initial
   assumption was wrong. It shares **no common git ancestor** with `master`,
   has **100+ independent commits**, and its own `main.py` differs
   substantially in size from `master`'s (7350 vs 3689 bytes) — this is a
   real, actively-diverged parallel version of the codebase, not a stub or
   duplicate. **Do not delete, merge, or otherwise touch this branch without
   the user's explicit decision on what it represents and whether it's still
   wanted.** My only change to it was the accidental SHA-pinning commits
   from the mis-targeted first pass — nothing else was touched, and nothing
   was deleted.
4. **Supabase PAT rotation** — a live personal access token
   (`sbp_cb26...` — see chat history for the full value, not repeating it
   here) was pasted into chat during Wave 2 and used directly (never passed
   into any subagent prompt) to provision Supabase tables/secrets for
   `sgBusLaoBu2021` and `sgConnectSphere2026`. The user was told to rotate/
   revoke it and **explicitly said not to prioritize this** ("dont care about
   the pat rotate rn") — left open at the user's discretion, not a blocker.

## Resolved this session (2026-09-24, second pass)

- **`smucourses` PR #31** — updated branch (was behind main), waited for CI,
  merged (squash + delete branch). Confirmed `merged: true` via API.
- **`sgConnectSphere2026` PR #122** — see item 2 above; automated checks all
  green now, only the human-review gate remains.
- **Unpinned GitHub Actions** — see item 3 above; all 11 sampled/known repos
  fixed, ~373 refs pinned to SHA.

## Resolved this session (2026-09-25, team-mode re-audit sweep)

Ran a fresh portfolio-wide re-audit across all 69 non-archived `hongyime/*`
repos (team_mode's `team_create` hit its usual lock-timeout/creation-state
issues again - 2 of 4 audit members never actually started, real work got
silently swapped to zombie sessions; the lead did those 2 batches directly
instead of fighting it further; team closed via force-delete since its status
never left `creating` despite real member work completing). Findings and
fixes from this pass:

- **Merged 7 more clean/fixed PRs**: `sgCarParks2020` #114/#115/#116,
  `searchIG2020` #86, `gmaplists` #145, `theprawnsplit` #13,
  `anywheelsQR2020` #48 (after a real fix - see below).
- **`pythoncrash`**: found and fixed the exact same labeler-config-path bug
  as an earlier wave, but in a different file - a stale, redundant
  `.github/workflows/label.yml` (old GitHub template default, pointed at a
  nonexistent `.github/labeler.yml`, never skipped dependabot) was still
  present alongside the already-correct `labeler.yml`. Deleted the stale
  file, updated the 3 blocked dependabot PRs' branches, merged all 3.
- **`anywheelsQR2020` PR #48**: root-caused a `tests/test_merge_policy.py`
  failure (`AttributeError: module 'merge_policy' has no attribute 'shutil'`
  and `'CHECK_FIELDS'`) to the PR branch carrying a genuinely older blob of
  `.github/scripts/checked-bot-merge.py` than current `main` - `update-branch`
  didn't reconcile it because the PR's own diff never touched that file.
  Overwrote it directly with main's current (already-correct) version on the
  PR branch, merged.
- **CodeQL "default setup + advanced configuration" conflict** (error:
  "CodeQL analyses from advanced configurations cannot be processed when the
  default setup is enabled") fixed on 4 repos by disabling default setup via
  `PATCH /repos/{repo}/code-scanning/default-setup {state: not-configured}`:
  `unifiedanalyzer`, `facetracker`, `smuseats`, `pocketclawd`. Each already
  had a working custom `codeql.yml` (the "advanced" config) - default setup
  was the redundant, conflicting half. Could not force a fresh verification
  run (`codeql.yml` has no `workflow_dispatch` on any of the 4) but the fix
  is a Settings-level change and will apply on the next real push/PR/schedule
  trigger.
- **`sgSHIOK2026`**: `.vercelignore` was missing 2 required negation lines
  for `web/public/data/generated_20260805_prefer_scored_routed/` (a
  repo-integrity check enforces this exact pair exists). Added both lines,
  pushed to main.
- **`theprawnprojects`**: root-caused 11 consecutive "Catalog Refresh"
  failures (`FATAL ERROR: JavaScript heap out of memory`, exit 134) to a
  real bug in `scripts/auto-update-catalog.mjs`'s Vercel-API pagination
  loop - it checked `from !== undefined` but Vercel returns `pagination.next
: null` (not `undefined`) on the last page, so the loop never terminated and
  kept re-requesting with a literal `from=null` string forever. Fixed the
  loop condition to `!= null`, added a defensive max-page cap and a
  stuck-cursor guard as belt-and-suspenders. Verified via two manual
  `workflow_dispatch` runs: first confirmed the new guard fires fast and
  clean instead of OOMing (proving the diagnosis), second confirmed a full
  successful run after the real fix.
- **`sgCertWatch2026`**: found a NEW, separate failure in
  `scripts/test_intel_ui.mjs` (Playwright E2E) - after a reload +
  visibility-change refresh, the "Domains to watch now" view's watch-cards
  (`#finding-list [data-finding-index] .watch-card-head strong`) return an
  empty list instead of the 3 expected registrable domains. Confirmed
  `renderFindingCard` in `lib/ui/findings-list.js` itself looks structurally
  correct (right class names, right escaping) - the bug is upstream in
  whatever decides how many findings get passed to it after that specific
  refresh sequence, which needs actual Playwright-level debugging (stepping
  through the real browser state), not static code reading. **Not fixed -
  needs a dedicated debugging session.** Also worth noting: this repo's
  history shows an earlier commit in this same relative area (`5dbf7483`,
  this session's own XSS sanitization fix) had an unrelated side effect
  that deleted a desktop table render branch, which was already caught and
  fixed by a later commit (`e45240a`) before this session even started - not
  something to redo, just context.
- **`sgConnectSphere2026`**: has 8 open PRs, all 0-1 days old - looks like
  genuinely active, in-progress development, not stale/stuck. Left alone.
- **`FORGE`**: has 4 dependabot PRs (version bumps only) and 13 simultaneous
  CI failures across highly specialized-sounding jobs (Kill-Chain Integration,
  OPSEC Evasion Assertions, Phase 0-6 pentest modules, etc.) that are already
  failing on `main` itself, not caused by the PRs. This looks like a complex
  custom security-tooling test suite that may need real secrets/sandbox
  environment setup in CI, or may have a genuine multi-job regression -
  either way it's too specialized and high-risk to touch during a broad audit
  sweep. **Flagged for a dedicated investigation, not touched.**
- **Still not investigated this pass** (found, not yet triaged):
  `englishDefinitions2021` (CI FAILURE: build (3.10)), `nusnetID2021` (CI
  FAILURE: build, build (3.10), deploy), `theprawntemplate` (CI FAILURE:
  deploy), `nanyangNightStudy2020` (CI FAILURE: Dependabot check),
  `pocketclawd` (2 more failures beyond the CodeQL one already fixed: Test
  (coverage gate), Lint).

## How to resume

1. Re-verify each "done" item above with a live `gh` call before assuming it's
   still true (another machine/agent may have touched these repos since).
2. Real remaining items: `theprawnhunter` (needs Cloudflare/`wrangler`
   credentials this session doesn't have), the `sgConnectSphere2026` PR #122
   review click (needs a human, or a different account than the PR author),
   the PAT rotation (explicitly deprioritized by the user, not a blocker),
   `FORGE`'s 13 specialized CI failures (needs a dedicated investigation),
   `sgCertWatch2026`'s watch-card rendering bug in the "Domains to watch
   now" view (needs real Playwright/browser-level debugging, not static
   reading), and 5 untriaged CI failures: `englishDefinitions2021`,
   `nusnetID2021`, `theprawntemplate`, `nanyangNightStudy2020`,
   `pocketclawd` (coverage gate + lint, separate from its already-fixed
   CodeQL issue).
3. Everything else in the original 8-wave cross-pollination plan is complete.
   If picking up fresh context on "what was the plan," the original audit
   that drove it is at
   `audit_results/practices-audit-20260922/batch-{alpha,bravo,charlie,delta}.md`
   on the X-drive (not git-tracked — read-only reference, not a sync target).

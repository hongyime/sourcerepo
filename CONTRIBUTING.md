# Contributing

Thanks for your interest in contributing!

## Getting started

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit using [Conventional Commits](https://www.conventionalcommits.org): `feat:`, `fix:`, `chore:`, `docs:`, etc.
4. Open a pull request against `main`

## Guidelines

- Keep PRs focused — one logical change per PR
- No commented-out code or leftover debug statements
- Update documentation if behaviour changes
- Secrets must never be committed — TruffleHog scans every PR

## Catalog reconciliation

The scheduled reconciliation job discovers only `hongyime` repositories. It
keeps unresolved and foreign-owner catalog entries in place and does not infer
deletion from an inaccessible repository. Generated PR bodies use this repo's
Summary, Changes, Testing and Checklist sections; their unchecked review items
are not claims that validation has passed.

An existing reconciliation PR pauses automated publication until that review is
resolved. This can delay newly discovered catalog additions, but preserves the
branch, description and review history. New work uses a unique
`chore/reconcile-repos-<run>-<attempt>` branch and an ordinary push; reconciliation
never force-pushes, closes PRs or deletes review branches.

Run `python -B -m unittest discover -s tests -p test_reconcile_repos.py -v`
for offline discovery, catalog, report and review-preservation checks. They use
synthetic inventory and temporary local repositories, with no real GitHub calls.

## Reporting bugs

Use the [bug report](.github/ISSUE_TEMPLATE/bug_report.md) issue template.

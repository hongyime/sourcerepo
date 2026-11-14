# Shared skills retirement

The repository-wide `skills/` bundle and `skills-lock.json` have been retired.
They are no longer synchronized to downstream repositories.

Install skills in the local harness that needs them. The single home for
skills is hongyime/theprawnskills — install from there (see its README for
the installer and profiles). Shared, durable agent instructions belong in
`AGENTS.md`; cross-session project state belongs in `.agents/`.

The SHELL house standard (repo tiers, Apache-2.0 licensing, GitHub
metadata, README identity, secret scanning) no longer lives in this repo —
`STANDARD.md` was retired on 2026-11-14. The standard now lives in the
`repo-standardization` skill in hongyime/theprawnskills.

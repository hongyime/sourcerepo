#!/usr/bin/env bash
set -euo pipefail

# INCLUDE_ARCHIVED flag comes from the calling workflow. Default true so a
# direct manual invocation of this script hits every non-disabled repo.
INCLUDE_ARCHIVED="${INCLUDE_ARCHIVED:-true}"

git config --global user.email "actions@github.com"
git config --global user.name "GitHub Actions Sync"

OWNER="${GITHUB_REPOSITORY_OWNER}"
SOURCE_REPO_NAME="${GITHUB_REPOSITORY##*/}"
WORKDIR="$(pwd)"
SYNC_ROOT="$(mktemp -d)"
FAILED_REPOS=()
PUSH_FAILED_REPOS=()
REARCHIVE_FAILED_REPOS=()
declare -A CASE_PATHS_BY_LOWER=()
CASE_PATHS_READY=false

# Combined repo list: hongyime org repos + personal-account owned repos.
# Personal repos are the profile README + Pages site (kept under the personal
# account because GitHub's magic profile/pages only render at the matching user
# path). Any future personal-account repos are picked up automatically.
# Fetch separately: an earlier failure inside a command group must not be
# hidden by a successful later request and reported as a complete sync.
ORG_REPOS_JSON="$(gh api --paginate "orgs/hongyime/repos?per_page=100")"
PERSONAL_REPOS_JSON="$(gh api --paginate "user/repos?per_page=100&affiliation=owner")"
REPOS_JSON="$(printf '%s\n%s\n' "$ORG_REPOS_JSON" "$PERSONAL_REPOS_JSON" |
  jq -s 'add | unique_by(.full_name) | map(select(.disabled == false and .fork == false))')"

GITIGNORE_MARKER="# AI / editor dot directories (managed via sourcerepo)"
GITIGNORE_END_MARKER="# End AI / editor dot directories (managed via sourcerepo)"

retry() {
  local attempts=0
  local max_attempts=3
  until "$@"; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$max_attempts" ]; then
      return 1
    fi
    sleep $((2 ** attempts))
  done
}

validate_copy_destination() {
  local src="$1" dst="$2" parent="$2"
  # A managed path must not redirect a copy through app-owned links.
  while [ "$parent" != "." ] && [ "$parent" != "/" ]; do
    if [ -L "$parent" ]; then
      echo "Preserving linked destination; config copy refused: $dst" >&2
      return 1
    fi
    parent="$(dirname "$parent")"
  done
  if [ -L "$src" ] || { [ -e "$dst" ] && {
    { [ -f "$src" ] && [ ! -f "$dst" ]; } ||
    { [ -d "$src" ] && [ ! -d "$dst" ]; }
  }; }; then
    echo "Preserving conflicting destination; config copy refused: $dst" >&2
    return 1
  fi
}

copy_if_exists() {
  local src="$1"
  local dst="$2"
  local dst_dir
  dst_dir="$(dirname "$dst")"
  if [ -f "$src" ]; then
    validate_copy_destination "$src" "$dst" || return 1
    mkdir -p "$dst_dir" || return 1
    cp -f "$src" "$dst" || return 1
    echo "Copied file $src -> $dst"
  elif [ -d "$src" ]; then
    validate_copy_destination "$src" "$dst" || return 1
    # Validate the complete managed tree, then merge it. Files absent from
    # sourcerepo remain owned by the application and must survive the sync.
    local entry
    while IFS= read -r -d '' entry; do
      validate_copy_destination "$entry" "$dst/${entry#"$src"/}" || return 1
    done < <(find "$src" -mindepth 1 -print0)
    mkdir -p "$dst" || return 1
    cp -r "$src/." "$dst/" || return 1
    echo "Copied directory $src -> $dst"
  else
    echo "Source missing, skipping copy: $src"
  fi
}

force_stage_path() {
  local path="$1"
  if [ -e "$path" ]; then
    git add -f "$path"
  else
    git add -A "$path" 2>/dev/null || true
  fi
}

build_case_path_index() {
  CASE_PATHS_BY_LOWER=()
  while IFS= read -r path; do
    local lower_path="${path,,}"
    if [ -n "${CASE_PATHS_BY_LOWER[$lower_path]+x}" ]; then
      CASE_PATHS_BY_LOWER[$lower_path]+=$'\n'"$path"
    else
      CASE_PATHS_BY_LOWER[$lower_path]="$path"
    fi
  done < <(git ls-files)
  CASE_PATHS_READY=true
}

case_conflicting_paths() {
  local dst="$1"
  local lower_dst="${dst,,}"
  if [ "$CASE_PATHS_READY" != "true" ]; then
    build_case_path_index
  fi

  local paths="${CASE_PATHS_BY_LOWER[$lower_dst]-}"
  [ -z "$paths" ] && return 0

  while IFS= read -r path; do
    if [ "$path" != "$dst" ]; then
      printf '%s\n' "$path"
    fi
  done <<< "$paths"
}

remove_case_conflicts_for() {
  local dst="$1"
  local conflicts=()
  mapfile -t conflicts < <(case_conflicting_paths "$dst")
  for path in "${conflicts[@]}"; do
    echo "Removing case-conflicting tracked path: $path (canonical: $dst)"
    git rm -f --cached -- "$path" >/dev/null 2>&1 || true
    rm -f -- "$path" 2>/dev/null || true
  done
}

should_skip_case_conflicting_sync() {
  local dst="$1"
  local conflicts=()
  mapfile -t conflicts < <(case_conflicting_paths "$dst")
  [ "${#conflicts[@]}" -eq 0 ] && return 1

  case "$dst" in
    AGENTS.md)
      echo "Skipping AGENTS.md sync because target has case-conflicting repo-specific file(s): ${conflicts[*]}"
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

inject_gitignore_entries() {
  if grep -qF "$GITIGNORE_MARKER" .gitignore 2>/dev/null; then
    local cleaned
    cleaned="$(mktemp)"
    if grep -qF "$GITIGNORE_END_MARKER" .gitignore 2>/dev/null; then
      awk -v start="$GITIGNORE_MARKER" -v end="$GITIGNORE_END_MARKER" '
        $0 == start { skip=1; next }
        skip && $0 == end { skip=0; next }
        !skip { print }
      ' .gitignore > "$cleaned"
    else
      awk -v start="$GITIGNORE_MARKER" '
        $0 == start { skip=1; next }
        skip && $0 == "docs/" { skip=0; next }
        !skip { print }
      ' .gitignore > "$cleaned"
    fi
    mv "$cleaned" .gitignore
  fi
  cat >> .gitignore << 'GITIGNORE_BLOCK'

# AI / editor dot directories (managed via sourcerepo)
.*
!.github/
!.agents/
.agents/*
!.agents/STATE.md
!.agents/JOURNAL.md
!.agents/handoffs/
!.agents/handoffs/**
!.gitignore
!.gitattributes
!.gitmodules
!.editorconfig
!.nvmrc
!.node-version
!.python-version
!.tool-versions
!.prettierrc*
!.eslintrc*
!.stylelintrc*
!.babelrc*
!.browserslistrc
!.dockerignore
!.npmrc
!.yarnrc
!.yarnrc.yml
!.env.example
!.env.template
!.env.sample
!.sourcery.yml
!.deepsource.toml
skills/
skills-lock.json
docs/
# End AI / editor dot directories (managed via sourcerepo)
GITIGNORE_BLOCK
  echo "Updated .gitignore with dot directory exclusions"
}

# Unarchive a repo (returns 0 on success, non-zero on failure)
unarchive_repo() {
  local full_name="$1"
  gh api -X PATCH "repos/$full_name" -f archived=false >/dev/null
}

# Re-archive a repo
rearchive_repo() {
  local full_name="$1"
  gh api -X PATCH "repos/$full_name" -f archived=true >/dev/null
}

REPOS_JSON="$REPOS_JSON"
echo "Owner: $OWNER"
echo "Source repo: $SOURCE_REPO_NAME"
echo "Include archived: $INCLUDE_ARCHIVED"
echo "Found repos: $(echo "$REPOS_JSON" | jq length)"

while read -r repo; do
  REPO_NAME="$(echo "$repo" | jq -r '.name')"
  REPO_OWNER="$(echo "$repo" | jq -r '.owner.login')"
  ARCHIVED="$(echo "$repo" | jq -r '.archived')"
  DISABLED="$(echo "$repo" | jq -r '.disabled')"
  FORKED="$(echo "$repo" | jq -r '.fork')"
  DEFAULT_BRANCH="$(echo "$repo" | jq -r '.default_branch')"
  FULL_NAME="$REPO_OWNER/$REPO_NAME"

  # Disabled repos still cannot be interacted with (different from archived).
  if [ "$DISABLED" = "true" ] || [ "$FORKED" = "true" ]; then
    echo "Skipping repo: $REPO_NAME (disabled=$DISABLED fork=$FORKED)"
    continue
  fi

  if [ "$ARCHIVED" = "true" ] && [ "$INCLUDE_ARCHIVED" != "true" ]; then
    echo "Skipping archived repo (per flag): $REPO_NAME"
    continue
  fi

  if [ "$REPO_NAME" = "$SOURCE_REPO_NAME" ]; then
    echo "Skipping source repo: $REPO_NAME"
    continue
  fi

  # Read opt-outs before cloning or changing archive state. Unknown metadata
  # is a failed check, never permission to replace application configuration.
  if ! REPO_TOPICS="$(gh api "repos/$FULL_NAME/topics" --jq '.names | join(",")')"; then
    echo "Cannot read topics for $FULL_NAME; skipping config sync" >&2
    FAILED_REPOS+=("$REPO_NAME")
    continue
  fi
  echo "Topics: ${REPO_TOPICS:-none}"
  if [[ ",$REPO_TOPICS," == *",no-config-sync,"* ]]; then
    echo "Skipping all config sync for $REPO_NAME (topic: no-config-sync)"
    continue
  fi

  # Temporarily unarchive so we can push to it.
  UNARCHIVED_HERE=false
  if [ "$ARCHIVED" = "true" ]; then
    echo "Temporarily unarchiving $FULL_NAME..."
    if unarchive_repo "$FULL_NAME"; then
      UNARCHIVED_HERE=true
    else
      echo "Failed to unarchive $FULL_NAME — skipping"
      FAILED_REPOS+=("$REPO_NAME")
      continue
    fi
  fi

  TARGET_DIR="$SYNC_ROOT/$REPO_NAME"
  echo "Processing $REPO_NAME..."

  if ! retry gh repo clone "$FULL_NAME" "$TARGET_DIR" -- --depth 1; then
    echo "Failed to clone $FULL_NAME, skipping."
    FAILED_REPOS+=("$REPO_NAME")
    # Restore archive state before continuing
    if [ "$UNARCHIVED_HERE" = "true" ]; then
      rearchive_repo "$FULL_NAME" || REARCHIVE_FAILED_REPOS+=("$REPO_NAME")
    fi
    continue
  fi

  cd "$TARGET_DIR" || {
    FAILED_REPOS+=("$REPO_NAME")
    if [ "$UNARCHIVED_HERE" = "true" ]; then
      rearchive_repo "$FULL_NAME" || REARCHIVE_FAILED_REPOS+=("$REPO_NAME")
    fi
    cd "$WORKDIR" || exit 1
    continue
  }
  CASE_PATHS_READY=false

  # Filter SYNC_ITEMS if repo opted out of LFS enforcement.
  EFFECTIVE_SYNC_ITEMS="$SYNC_ITEMS"
  if [[ ",$REPO_TOPICS," == *",keep-lfs,"* ]]; then
    echo "Skipping LFS-related items for $REPO_NAME (topic: keep-lfs)"
    EFFECTIVE_SYNC_ITEMS="$(echo "$SYNC_ITEMS" | grep -v -E '\.gitattributes|lfs-guard\.yml' || true)"
  fi

  # Copy content from sourcerepo
  # Only opted-in root-directory apps receive the activity-branch heartbeat.
  if [ -e ".github/branch-heartbeat.json" ] || [ -L ".github/branch-heartbeat.json" ]; then
    if ! python3 "$WORKDIR/.github/scripts/branch-heartbeat.py" --validate-config .github/branch-heartbeat.json; then
      echo "Invalid branch heartbeat opt-in for $FULL_NAME; skipping config sync" >&2
      FAILED_REPOS+=("$REPO_NAME")
      cd "$WORKDIR" || exit 1
      if [ "$UNARCHIVED_HERE" = "true" ]; then
        rearchive_repo "$FULL_NAME" || REARCHIVE_FAILED_REPOS+=("$REPO_NAME")
      fi
      continue
    fi
    EFFECTIVE_SYNC_ITEMS="${EFFECTIVE_SYNC_ITEMS/.github\/workflows\/heartbeat.yml|.github\/workflows\/heartbeat.yml/.github\/workflow-templates\/branch-heartbeat.yml|.github\/workflows\/heartbeat.yml}"
    EFFECTIVE_SYNC_ITEMS+=$'\n.github/scripts/branch-heartbeat.py|.github/scripts/branch-heartbeat.py'
  fi

  COPY_FAILED=false
  while IFS='|' read -r src dst; do
    [ -z "$src" ] && continue
    if should_skip_case_conflicting_sync "$dst"; then
      continue
    fi
    remove_case_conflicts_for "$dst"
    if ! copy_if_exists "$WORKDIR/$src" "$dst"; then
      FAILED_REPOS+=("$REPO_NAME")
      COPY_FAILED=true
      break
    fi
    force_stage_path "$dst"
  done <<< "$EFFECTIVE_SYNC_ITEMS"

  if [ "$COPY_FAILED" = "true" ]; then
    cd "$WORKDIR" || exit 1
    rm -rf "$TARGET_DIR"
    if [ "$UNARCHIVED_HERE" = "true" ]; then
      rearchive_repo "$FULL_NAME" || REARCHIVE_FAILED_REPOS+=("$REPO_NAME")
    fi
    continue
  fi

  # ── Per-repo heartbeat cron staggering (added 2026-08-04) ─────────────
  # All ~60 private repos previously shared the same Monday 09:00 UTC cron,
  # which fired concurrent heartbeat runners in a burst and wasted queue
  # time. Rewrite the cron minute to a stable hash-derived value in
  # [0, 59] so the load spreads across the whole hour. Deterministic in
  # repo name so re-syncs don't churn the file.
  HEARTBEAT_YML=".github/workflows/heartbeat.yml"
  if [ -f "$HEARTBEAT_YML" ]; then
    MINUTE=$(( 0x$(printf '%s' "$REPO_NAME" | md5sum | cut -c1-2) % 60 ))
    # Only rewrite the exact literal source line to avoid clobbering other crons.
    if grep -qE '^ *- cron: "0 9 \* \* 1"' "$HEARTBEAT_YML"; then
      sed -i -E "s|^( *- cron: \")0( 9 \\* \\* 1\")|\\1${MINUTE}\\2|" "$HEARTBEAT_YML"
      echo "Staggered heartbeat cron to minute=${MINUTE} for ${REPO_NAME}"
      force_stage_path "$HEARTBEAT_YML"
    fi
  fi

  # Unlisted application files, dot directories, skills, documentation and
  # editor workspaces are outside this sync's ownership. Preserve them.

  inject_gitignore_entries

  git add -A

  if [ -n "$(git status --porcelain)" ]; then
    git commit -m "$COMMIT_MESSAGE"
    if retry git push origin HEAD:"$DEFAULT_BRANCH"; then
      echo "Pushed changes to $REPO_NAME"
    else
      SYNC_BRANCH="sync-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
      git checkout -b "$SYNC_BRANCH"
      if git push origin "$SYNC_BRANCH"; then
        gh pr create --repo "$FULL_NAME" --title "$PR_TITLE" --body "$PR_BODY" --base "$DEFAULT_BRANCH" --head "$SYNC_BRANCH" || true
        echo "Opened PR for $REPO_NAME"
      else
        echo "Push failed for $REPO_NAME"
        PUSH_FAILED_REPOS+=("$REPO_NAME")
      fi
    fi
  else
    echo "No changes needed in $REPO_NAME, skipping push."
  fi

  cd "$WORKDIR" || exit 1
  rm -rf "$TARGET_DIR"

  # Restore archive state
  if [ "$UNARCHIVED_HERE" = "true" ]; then
    echo "Re-archiving $FULL_NAME..."
    if ! rearchive_repo "$FULL_NAME"; then
      echo "⚠️  Failed to re-archive $FULL_NAME — DO THIS MANUALLY"
      REARCHIVE_FAILED_REPOS+=("$REPO_NAME")
    fi
  fi
done < <(echo "$REPOS_JSON" | jq -c '.[] | {name, archived, disabled, fork, default_branch, owner}')

if [ "${#FAILED_REPOS[@]}" -gt 0 ]; then
  echo "Metadata/clone/unarchive/copy failures: ${FAILED_REPOS[*]}"
fi

if [ "${#PUSH_FAILED_REPOS[@]}" -gt 0 ]; then
  echo "Push failures: ${PUSH_FAILED_REPOS[*]}"
fi
if [ "${#REARCHIVE_FAILED_REPOS[@]}" -gt 0 ]; then
  echo "⚠️  RE-ARCHIVE FAILURES (manual action required): ${REARCHIVE_FAILED_REPOS[*]}"
  # Exit non-zero to surface this loudly in the Actions UI.
  exit 1
fi

if [ "${#FAILED_REPOS[@]}" -gt 0 ] || [ "${#PUSH_FAILED_REPOS[@]}" -gt 0 ]; then
  exit 1
fi

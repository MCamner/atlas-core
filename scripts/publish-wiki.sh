#!/usr/bin/env bash
set -euo pipefail

REPO_FULL_NAME="${REPO_FULL_NAME:-MCamner/atlas-core}"
WIKI_REMOTE="https://github.com/${REPO_FULL_NAME}.wiki.git"
WIKI_SOURCE_DIR="${WIKI_SOURCE_DIR:-wiki}"
WIKI_WORK_DIR="${WIKI_WORK_DIR:-.wiki-worktree}"

if [[ ! -d "$WIKI_SOURCE_DIR" ]]; then
  echo "ERROR: wiki source directory not found: $WIKI_SOURCE_DIR" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required" >&2
  exit 1
fi

rm -rf "$WIKI_WORK_DIR"

if ! git clone "$WIKI_REMOTE" "$WIKI_WORK_DIR"; then
  cat >&2 <<EOF
ERROR: Could not clone GitHub Wiki repo:
  $WIKI_REMOTE

Enable Wiki first:
  GitHub → MCamner/atlas-core → Settings → Features → Wikis

Then create the first wiki page once in the GitHub UI if GitHub has not created
${REPO_FULL_NAME}.wiki.git yet. After that, run this script again.
EOF
  exit 1
fi

find "$WIKI_WORK_DIR" -maxdepth 1 -type f -name '*.md' -delete
cp "$WIKI_SOURCE_DIR"/*.md "$WIKI_WORK_DIR"/

cd "$WIKI_WORK_DIR"

git add .

if git diff --cached --quiet; then
  echo "Wiki already up to date."
  exit 0
fi

git commit -m "Update Atlas Core wiki"
git push

echo "Wiki published: https://github.com/${REPO_FULL_NAME}/wiki"

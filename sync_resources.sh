#!/bin/bash
# Refreshes resources/ (the personas, the sample memo and the page_afp theme) from the AFP workshop
# folder. Run it inside the workshop repo after editing a persona or the theme; the standalone
# repo, the Mac build and the Windows build all read resources/.
set -euo pipefail
cd "$(dirname "$0")"
THINK_ASK="$(cd .. && pwd)"
WORKSHOP="$(cd ../.. && pwd)"
[ -f "$THINK_ASK/02-persona-skeptical-cfo.md" ] && [ -f "$WORKSHOP/styles/page_afp.css" ] || {
  echo "Not inside the AFP workshop folder: nothing to sync."; exit 1; }
mkdir -p resources/personas resources/styles
cp "$THINK_ASK"/0{2,3,4}-persona-*.md "$THINK_ASK/sample-draft-forecast-memo.md" resources/personas/
cp "$WORKSHOP/styles/page_afp.css" resources/styles/
echo "resources/ is up to date."

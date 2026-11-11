#!/bin/bash
# Builds dist/BoardReady.dmg: a self-contained Mac app that runs on any Apple-silicon Mac,
# with no workshop folder, no uv, no terminal.
#
# Inside the app: Python and its packages (PyInstaller), the web UI and website, copies of
# the three persona files, the sample memo and page_afp.css, plus Node and the Marp CLI for
# the HTML and PDF export (copied from this Mac: run `npx @marp-team/marp-cli@4.5.1 -v` once
# if the build says Marp was not found).
#
# Not inside: any API key. Each user adds theirs in the app's Settings.
# The personas are copied from resources/ at build time: after editing a persona file, run
# ./sync_resources.sh (inside the workshop folder), then build again.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
MARP_VERSION="4.5.1"
NAME="BoardReady"
BUILD="${TMPDIR:-/tmp}/boardready-build"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# Build in a clean environment: an active virtualenv (the workshop's .venv) would pull
# its whole data-science stack into the app.
unset VIRTUAL_ENV CONDA_PREFIX

rm -rf "$BUILD"
mkdir -p "$BUILD/data/personas" "$BUILD/data/styles" "$BUILD/dmg" dist

echo "1/6  Resources"
cp resources/personas/* "$BUILD/data/personas/"
cp resources/styles/page_afp.css "$BUILD/data/styles/"
rsync -a --exclude '.DS_Store' web site "$BUILD/data/"

echo "2/6  Icon"
mkdir -p "$BUILD/AppIcon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s web/icon.png --out "$BUILD/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) web/icon.png --out "$BUILD/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$BUILD/AppIcon.icns"

echo "3/6  App (PyInstaller, a few minutes the first time)"
uv run --isolated --no-project --python-preference only-managed --python 3.12 \
  --with pyinstaller --with anthropic --with openai --with openpyxl --with python-docx --with "pywebview>=5" \
  pyinstaller app.py --noconfirm --windowed --name "$NAME" \
    --icon "$BUILD/AppIcon.icns" \
    --osx-bundle-identifier com.datawiseacademy.boardready \
    --add-data "$BUILD/data/web:web" --add-data "$BUILD/data/site:site" \
    --add-data "$BUILD/data/personas:personas" --add-data "$BUILD/data/styles:styles" \
    --hidden-import review_engine \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
    --log-level WARN
APP="$BUILD/dist/$NAME.app"

echo "4/6  Marp export (Node + Marp CLI from this Mac)"
NODE="$(command -v node || ls -d "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | tail -1 || true)"
MARP_DIR=""
for d in "$HOME"/.npm/_npx/*/node_modules; do
  if grep -q "\"version\": \"$MARP_VERSION\"" "$d/@marp-team/marp-cli/package.json" 2>/dev/null; then MARP_DIR="$d"; break; fi
done
if [ -n "$NODE" ] && [ -n "$MARP_DIR" ]; then
  mkdir -p "$APP/Contents/Resources/marp"
  cp "$NODE" "$APP/Contents/Resources/marp/node"
  # A universal Node carries an Intel copy too; the app is Apple-silicon only, so keep arm64.
  if [ "$(lipo -archs "$NODE" 2>/dev/null | wc -w)" -gt 1 ]; then
    lipo "$NODE" -thin arm64 -output "$APP/Contents/Resources/marp/node"
  fi
  rsync -a "$MARP_DIR/" "$APP/Contents/Resources/marp/node_modules/"
  echo "     Bundled Node $("$NODE" --version) and Marp CLI $MARP_VERSION."
else
  echo "     Node or Marp CLI $MARP_VERSION not found: the app will write Markdown, and use npx if the user has Node."
fi

# Product name in the menu bar, and an ad-hoc signature over the finished bundle
# (Apple-silicon Macs refuse to run unsigned code).
/usr/libexec/PlistBuddy -c "Set :CFBundleName $NAME" -c "Add :CFBundleDisplayName string $NAME" \
  -c "Set :CFBundleShortVersionString 1.0" "$APP/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep --sign - "$APP"

echo "5/6  Smoke test"
"$APP/Contents/MacOS/$NAME" --help | sed -n 2p

echo "6/6  Disk image"
cp -R "$APP" "$BUILD/dmg/"
ln -s /Applications "$BUILD/dmg/Applications"
cat > "$BUILD/dmg/Read Me First.txt" <<'TXT'
BoardReady
Put your draft in front of the panel before it goes in front of the board.

INSTALL
1. Drag BoardReady onto the Applications folder.
2. The first time only: right-click BoardReady in Applications and choose Open,
   then Open again. (The app is not notarized by Apple, so macOS asks once.)
   If macOS still refuses: System Settings > Privacy & Security > Open Anyway.
3. Click Settings, choose your provider and model, and paste your API key.
   The key stays on your Mac, in ~/Library/Application Support/BoardReady.

USE
Drop a Markdown, Word (.docx), Excel (.xlsx) or CSV file. Tick the personas
(Elena Varga the Skeptical CFO, the Group Controller, the Red-Team Reviewer)
and what you expect from them (criticize, review for consistency, suggest
enrichments). Reviews are saved in Documents/BoardReady as Markdown, HTML and PDF.

The PDF export needs Google Chrome (or Microsoft Edge) installed.
Requires a Mac with Apple silicon (M1 or later).

The personas are fictional. Read every review as a pre-mortem, not a verdict.
Data Wise Academy, AFP 2026 workshop.
TXT
rm -f "dist/$NAME.dmg"
hdiutil create -volname "$NAME" -srcfolder "$BUILD/dmg" -ov -format UDZO -fs HFS+ "dist/$NAME.dmg" 2>/dev/null >/dev/null
echo
echo "Built: $HERE/dist/$NAME.dmg ($(du -h "dist/$NAME.dmg" | cut -f1))"

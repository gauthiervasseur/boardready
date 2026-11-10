#!/bin/bash
# Builds "BoardReady.app" next to this script: a double-clickable Mac app
# that starts app.py in its own window. Run it again after moving the folder.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
APP="$HERE/BoardReady.app"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

echo "1/3  Icon"
TMP="$(mktemp -d)"
if [ -x "$CHROME" ]; then
  # Render the SVG icon at 1024 px on a transparent background.
  printf '<html><body style="margin:0;background:transparent"><img src="file://%s" width="1024" height="1024"></body></html>' "$HERE/web/icon.svg" > "$TMP/icon.html"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --default-background-color=00000000 \
    --allow-file-access-from-files --screenshot="$TMP/icon.png" --window-size=1024,1024 "file://$TMP/icon.html" >/dev/null 2>&1
fi
if [ -f "$TMP/icon.png" ]; then
  cp "$TMP/icon.png" web/icon.png
  mkdir -p "$TMP/AppIcon.iconset"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$TMP/AppIcon.iconset" -o "$TMP/AppIcon.icns"
else
  echo "     Google Chrome not found: the app keeps the default icon."
fi

echo "2/3  Bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
[ -f "$TMP/AppIcon.icns" ] && cp "$TMP/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>BoardReady</string>
  <key>CFBundleDisplayName</key><string>BoardReady</string>
  <key>CFBundleIdentifier</key><string>com.datawiseacademy.boardready</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>boardready</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# The launcher remembers where this folder is, so the app still works from /Applications.
cat > "$APP/Contents/MacOS/boardready" <<LAUNCHER
#!/bin/bash
DIR="$HERE"
[ -f "\$DIR/app.py" ] || DIR="\$(cd "\$(dirname "\$0")/../../.." && pwd)"
LOG="\$HOME/Library/Logs/BoardReady.log"
# Finder starts apps with a bare PATH: add uv, Homebrew and nvm's Node (for the Marp export).
PATH="\$HOME/.local/bin:\$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
for d in "\$HOME"/.nvm/versions/node/*/bin; do [ -d "\$d" ] && PATH="\$d:\$PATH"; done
export PATH
cd "\$DIR" || exit 1
echo "--- \$(date) starting from \$DIR" >> "\$LOG"
if [ ! -f app.py ]; then
  osascript -e 'display alert "BoardReady" message "The document review folder was not found. Run build_app.sh again from its new place."'
elif command -v uv >/dev/null 2>&1; then
  exec uv run --script app.py >> "\$LOG" 2>&1
elif python3 -c "import webview, anthropic" >/dev/null 2>&1; then
  exec python3 app.py >> "\$LOG" 2>&1
else
  osascript -e 'display alert "BoardReady needs uv" message "Install uv from docs.astral.sh/uv, or run: pip install -r requirements.txt"'
fi
LAUNCHER
chmod +x "$APP/Contents/MacOS/boardready"
touch "$APP"   # make Finder pick up the new icon

echo "3/3  Python packages"
if command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]; then
  PATH="$HOME/.local/bin:$PATH" uv run --script app.py --help >/dev/null && echo "     Ready (uv environment cached)."
else
  echo "     uv not found: install it, or run pip install -r requirements.txt"
fi
rm -rf "$TMP"
echo
echo "Built: $APP"
echo "Double-click it, or drag it to Applications or the Dock. Logs: ~/Library/Logs/BoardReady.log"

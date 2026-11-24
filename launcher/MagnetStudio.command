#!/bin/bash
# MagnetStudio launcher for macOS (Apple Silicon) - double-click it. First time: right-click -> Open.
# Keeps a ready-made MagnetStudio.app next to this file (folder "MagnetStudio-app") and starts it.
# Every start: asks GitHub whether a newer build exists; if so, downloads it (~45 MB) and swaps it in.
# Offline (e.g. at an event): just starts the version that is already here.
# The repo is private, so a read-only GitHub token is needed; it is asked for once and kept in the
# macOS Keychain. Your settings, templates and print counter are never touched.
set -u
REPO=gpzboy-creator/magnet-studio
ASSET=MagnetStudio-macOS-AppleSilicon.zip
HERE="$(cd "$(dirname "$0")" && pwd)"
APPROOT="$HERE/MagnetStudio-app"
APP="$APPROOT/MagnetStudio.app"
STAMP="$APPROOT/build-id.txt"
KC=MagnetStudio-updater
TOKEN_URL=https://github.com/settings/personal-access-tokens/new
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

read_token() {
    if [ -n "${MAGNETSTUDIO_UPDATER_TOKEN:-}" ]; then echo "$MAGNETSTUDIO_UPDATER_TOKEN"; return; fi
    security find-generic-password -s "$KC" -a github -w 2>/dev/null
}
save_token() { [ -n "${MAGNETSTUDIO_UPDATER_TOKEN:-}" ] || security add-generic-password -U -s "$KC" -a github -w "$1" >/dev/null; }
ask_token() {
    if [ -n "${MAGNETSTUDIO_UPDATER_TOKEN:-}" ]; then echo "The token in MAGNETSTUDIO_UPDATER_TOKEN was refused." >&2; return 1; fi
    {
        echo
        echo "MagnetStudio needs a read-only GitHub key to download updates (one time only)."
        echo "Opening $TOKEN_URL in your browser. There:"
        echo "  Token name: MagnetStudio      Expiration: the longest offered"
        echo "  Repository access: Only select repositories -> magnet-studio"
        echo "  Permissions -> Repository permissions -> Contents: Read-only"
        echo "  Generate token -> Copy"
    } >&2
    open "$TOKEN_URL"
    local t; read -r -s -p "Paste the token here (it stays hidden) and press Enter: " t; echo >&2
    t="$(printf '%s' "$t" | tr -d '[:space:]')"; [ -n "$t" ] || return 1
    printf '%s' "$t"
}
get_release() {  # $1 = token → $TMP/rel.json; prints the HTTP code (000 = offline)
    curl -sS --max-time 20 -o "$TMP/rel.json" -w '%{http_code}' -H "Authorization: Bearer $1" \
        -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$REPO/releases/tags/latest" 2>/dev/null || true
}
asset_info() {  # → "id<TAB>url<TAB>size<TAB>release name" (JSON parsed by macOS' own JavaScript)
    cat > "$TMP/p.js" <<'JS'
ObjC.import('Foundation');
function run(argv) {
  var r = JSON.parse($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null).js);
  var a = (r.assets || []).filter(function (x) { return x.name === argv[1]; })[0];
  return a ? [a.id, a.url, a.size, r.name].join('\t') : '';
}
JS
    osascript -l JavaScript "$TMP/p.js" "$TMP/rel.json" "$ASSET"
}

update_app() {
    local tok asked=0 code info id url size name have
    tok="$(read_token)"
    if [ -z "$tok" ]; then tok="$(ask_token)" || return 1; asked=1; fi
    code="$(get_release "$tok")"
    if [ "$code" = 401 ] || [ "$code" = 403 ] || [ "$code" = 404 ]; then
        echo "GitHub refused the key (HTTP $code) - it may be mistyped or expired. Let's make a new one."
        tok="$(ask_token)" || return 1; asked=1
        code="$(get_release "$tok")"
    fi
    [ "$code" = 200 ] || { echo "Could not reach GitHub (HTTP $code)."; return 1; }
    [ "$asked" = 1 ] && { save_token "$tok"; echo "Key saved in the Keychain."; }
    info="$(asset_info)"
    [ -n "$info" ] || { echo "The latest release has no $ASSET yet (a build may be running) - try again in a few minutes."; return 1; }
    IFS=$'\t' read -r id url size name <<< "$info"
    have="$(cat "$STAMP" 2>/dev/null || true)"
    if [ "$id" = "$have" ]; then echo "MagnetStudio is up to date - $name"; return 0; fi
    echo "Downloading $name ($((size / 1048576)) MB)..."
    curl -fL --max-time 900 -H "Authorization: Bearer $tok" -H "Accept: application/octet-stream" \
        -o "$TMP/app.zip" "$url" || { echo "Download failed."; return 1; }
    while pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; do echo "Close MagnetStudio to finish the update..."; sleep 3; done
    rm -rf "$APPROOT.new" "$APPROOT.old"
    ditto -x -k "$TMP/app.zip" "$APPROOT.new" || return 1
    [ -d "$APPROOT.new/MagnetStudio.app" ] || { echo "The download looks incomplete - try again."; return 1; }
    [ -d "$APPROOT" ] && mv "$APPROOT" "$APPROOT.old"
    mv "$APPROOT.new" "$APPROOT" && echo "$id" > "$STAMP"
    rm -rf "$APPROOT.old"
    echo "Updated to $name"
}

if ! update_app; then
    if [ -d "$APP" ]; then echo "Could not check for updates - starting the version you have."
    else echo "Could not download MagnetStudio. Connect to the internet and try again."; read -r -p "Press Enter to close" _; exit 1; fi
fi
echo "Starting MagnetStudio..."
if [ -n "${MAGNETSTUDIO_UPDATER_WAIT:-}" ]; then exec "$APP/Contents/MacOS/MagnetStudio"; else open "$APP"; fi

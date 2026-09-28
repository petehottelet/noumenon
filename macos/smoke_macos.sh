#!/bin/bash
# Compile a native smoke host, load the universal saver, and save receipts.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="$HERE/../dist"
BUNDLE="${1:-$DIST/Noumenon.saver}"
RECEIPTS="${2:-$DIST/macos-smoke}"
EXPECTED="$HERE/../native-catalog.json"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "The native ScreenSaverView smoke test requires macOS." >&2
    exit 1
fi
mkdir -p "$RECEIPTS"
xcrun clang -fobjc-arc -Wall -Wextra \
    -framework AppKit -framework ScreenSaver \
    "$HERE/smoke_macos.m" -o "$RECEIPTS/Noumenon-macos-smoke"

# The live feed fixture and edge cases every native port is checked against,
# plus a link and a pipe, which are never read.
# The edge-case feed stays out of the receipts folder: it holds a pipe.
ROOT="$HERE/.."
FIXTURE="$ROOT/tests/fixtures/live-feed"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
EDGE="$SCRATCH/live-feed"
(cd "$ROOT" && python3 -m live.feedcheck build "$EDGE" >/dev/null)
ln -s /etc/hosts "$EDGE/20260927T120000-000024.svg"
mkfifo "$EDGE/20260927T120000-000025.svg"

"$RECEIPTS/Noumenon-macos-smoke" "$BUNDLE" "$RECEIPTS" "$EXPECTED" "$FIXTURE" "$EDGE"
(cd "$ROOT" && python3 -m live.feedcheck check "$FIXTURE" "$RECEIPTS/live-fixture.json")
(cd "$ROOT" && python3 -m live.feedcheck check "$EDGE" "$RECEIPTS/live-edge_cases.json")

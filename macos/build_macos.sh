#!/bin/bash
# Build Noumenon.saver on macOS. Requires only the Xcode command-line tools.
#     bash macos/build_macos.sh
# Outputs: dist/Noumenon.saver and dist/Noumenon-macos-universal.zip
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="$HERE/../dist"
BUNDLE="$DIST/Noumenon.saver"
MIN="12.0"
ARCHIVE="$DIST/Noumenon-macos-universal.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Build this native bundle on macOS with the Xcode command-line tools." >&2
    exit 1
fi

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

build_slice() {
    local arch="$1"
    xcrun swiftc -O -parse-as-library \
        -target "$arch-apple-macos$MIN" \
        -emit-library -module-name Noumenon \
        -framework AppKit -framework ScreenSaver \
        -o "$DIST/Noumenon-$arch" \
        "$HERE/NoumenonView.swift"
}

build_slice arm64
build_slice x86_64
lipo -create -output "$BUNDLE/Contents/MacOS/Noumenon" \
    "$DIST/Noumenon-arm64" "$DIST/Noumenon-x86_64"
lipo "$BUNDLE/Contents/MacOS/Noumenon" -verify_arch arm64 x86_64
rm -f "$DIST/Noumenon-arm64" "$DIST/Noumenon-x86_64"

cp "$HERE/Info.plist" "$BUNDLE/Contents/Info.plist"
cp "$HERE/glyphs.json" "$BUNDLE/Contents/Resources/glyphs.json"
cp "$HERE/../svg-preview/reference/LICENSE" "$BUNDLE/Contents/Resources/THIRD_PARTY_NOTICES.txt"
chmod 755 "$BUNDLE/Contents/MacOS/Noumenon"
plutil -lint "$BUNDLE/Contents/Info.plist"

# Bind bundle resources with an ad-hoc signature. Trusted downloaded
# distribution requires a Developer ID signature and notarization.
codesign --force --deep --sign - "$BUNDLE"
codesign --verify --strict --verbose=2 "$BUNDLE"

# Preserve the .saver hierarchy and executable modes across artifact downloads.
ditto -c -k --sequesterRsrc --keepParent "$BUNDLE" "$ARCHIVE"

echo "Built $BUNDLE"
echo "Packaged $ARCHIVE"
echo "Verify: bash $HERE/smoke_macos.sh"
echo "Install: double-click Noumenon.saver, or copy it to ~/Library/Screen Savers/"

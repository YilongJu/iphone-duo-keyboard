#!/usr/bin/env bash
# Signs the app and the keyboard extension of an archive ad hoc, each with the entitlements file
# of its target, and checks that both signatures hold the app group.
#
# The TestFlight workflow archives with signing off. An unsigned bundle holds no entitlements,
# and the export takes the entitlements from the signatures of the archive, so without this step
# the exported build would lack the app group of the speed test models. The export then signs
# again with the distribution certificate and keeps these entitlements.
# Usage: sign_with_entitlements.sh ARCHIVE.xcarchive
set -euo pipefail
archive="$1"
app="$archive/Products/Applications/DuoKeyboard.app"
appex="$app/PlugIns/DuoKeyboardExtension.appex"
group="group.com.yilongju.duokeyboard"
test -d "$appex"
# The inner bundle first, because the signature of the app covers the signatures inside it.
codesign --force --sign - --entitlements Keyboard/DuoKeyboardExtension.entitlements "$appex"
codesign --force --sign - --entitlements App/DuoKeyboard.entitlements "$app"
for bundle in "$appex" "$app"; do
  if ! codesign -d --entitlements - "$bundle" 2>/dev/null | grep -q "$group"; then
    echo "error: the signature of $bundle does not hold the app group $group" >&2
    codesign -d --entitlements - "$bundle" >&2 || true
    exit 1
  fi
  echo "the signature of $(basename "$bundle") holds the app group $group"
done

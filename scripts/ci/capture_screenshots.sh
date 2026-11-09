#!/usr/bin/env bash
# Runs on the macOS build machine. Installs the simulator build of the host app on each
# simulator, opens the field that always shows Duo Keyboard, and saves one screenshot per device.
#
# Usage: capture_screenshots.sh <path to DuoKeyboard.app> <output folder>
set -euo pipefail

app_path="$1"
output_dir="$2"
bundle_id="com.duokeyboard.app"
mkdir -p "$output_dir"

xcrun simctl list devices available > "$output_dir/available-devices.txt"

# Each line is a device name prefix. The first available simulator whose name starts with the
# prefix is used. The script stops when a prefix does not match any simulator.
# Saves one screenshot per display. The iPhone Duo simulator has two displays (inner and outer),
# and simctl then asks for a --display value and lists the valid ones in its error text.
capture() {
  local udid="$1" base="$2" message
  if message=$(xcrun simctl io "$udid" screenshot "$base.png" 2>&1); then
    return 0
  fi
  local ids
  ids=$(echo "$message" | sed -n 's/.*--display=\([0-9][0-9]*\).*//p')
  if [ -z "$ids" ]; then
    echo "$message" >&2
    return 1
  fi
  for id in $ids; do
    xcrun simctl io "$udid" screenshot --display="$id" "$base-display$id.png"
  done
}

prefixes=("iPhone Duo" "iPhone 17" "iPad Pro 13")

for prefix in "${prefixes[@]}"; do
  udid=$(xcrun simctl list devices available -j | python3 -c '
import json, sys
prefix = sys.argv[1]
devices = json.load(sys.stdin)["devices"]
for runtime in sorted(devices, reverse=True):
    for device in devices[runtime]:
        if device["name"].startswith(prefix):
            print(device["udid"])
            sys.exit(0)
sys.exit("simulator not found: " + prefix)
' "$prefix")
  slug=$(echo "$prefix" | tr ' ' '-')
  echo "== $prefix ($udid)"
  xcrun simctl boot "$udid"
  xcrun simctl bootstatus "$udid" -b
  xcrun simctl install "$udid" "$app_path"
  xcrun simctl ui "$udid" appearance light
  xcrun simctl launch "$udid" "$bundle_id" -focusPreviewField
  sleep 12
  capture "$udid" "$output_dir/$slug-light"
  xcrun simctl ui "$udid" appearance dark
  sleep 4
  capture "$udid" "$output_dir/$slug-dark"
  xcrun simctl shutdown "$udid"
done

ls -l "$output_dir"

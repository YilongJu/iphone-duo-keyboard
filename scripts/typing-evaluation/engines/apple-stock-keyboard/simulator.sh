#!/usr/bin/env bash
# Runs on the macOS runner. Creates a new iPhone simulator for the stock-keyboard measurement
# and sets the keyboard of that simulator.
#
# Usage:
#   simulator.sh create <name>                  prints the id of a new iPhone 17 simulator
#   simulator.sh configure <id> english|pinyin  boots the simulator, writes the keyboard settings,
#                                               restarts the simulator and prints the settings
#
# A new simulator starts without typing history, so one job cannot teach the keyboard of
# another job. The english simulator keeps the keyboards a new simulator has. The pinyin
# simulator gets the Simplified Chinese Pinyin keyboard with the QWERTY layout as its only keyboard.
set -euo pipefail

pinyin_keyboard='zh_Hans-Pinyin@sw=Pinyin-Simplified;hw=Automatic'

command="$1"
case "$command" in
  create)
    name="$2"
    # The newest iOS runtime that already holds an iPhone 17 gives the device type and the runtime.
    choice=$(xcrun simctl list devices available -j | python3 -c '
import json, re, sys
devices = json.load(sys.stdin)["devices"]
def version(runtime):
    return [int(part) for part in re.findall(r"\d+", runtime.rsplit(".", 1)[-1])]
for runtime in sorted((name for name in devices if "SimRuntime.iOS" in name), key=version, reverse=True):
    for device in devices[runtime]:
        if device["name"] == "iPhone 17":
            print(device["deviceTypeIdentifier"], runtime)
            sys.exit(0)
sys.exit("simulator not found: iPhone 17")
')
    read -r device_type runtime <<<"$choice"
    echo "device type $device_type, runtime $runtime" >&2
    xcrun simctl create "$name" "$device_type" "$runtime"
    ;;
  configure)
    udid="$2"
    task="$3"
    # The next lines only print facts for the run log: the runtime of the simulator and the
    # language data inside that runtime. A missing field does not stop the measurement.
    echo "== Runtime of the simulator"
    runtime_root=$(xcrun simctl list -j | python3 -c '
import json, sys
listing = json.load(sys.stdin)
udid = sys.argv[1]
for runtime_id, devices in listing.get("devices", {}).items():
    if any(device.get("udid") == udid for device in devices):
        for runtime in listing.get("runtimes", []):
            if runtime.get("identifier") == runtime_id:
                print(runtime.get("name"), "version", runtime.get("version"), "build", runtime.get("buildversion"), file=sys.stderr)
                print(runtime.get("runtimeRoot", ""))
' "$udid") || runtime_root=""
    echo "runtime root: $runtime_root"
    echo "== Language data that ships inside the runtime"
    ls "$runtime_root/System/Library/LinguisticData" || echo "(the listing of System/Library/LinguisticData did not work)"
    find "$runtime_root/System/Library/LinguisticData" -maxdepth 3 \( -name '*.lm' -o -name 'unilm*' \) | head -n 40 || true

    # Xcode 26 and earlier read this setting, and it keeps the software keyboard on screen there.
    defaults write com.apple.iphonesimulator ConnectHardwareKeyboard -bool false
    xcrun simctl boot "$udid"
    xcrun simctl bootstatus "$udid" -b
    echo "== Keyboard settings of the new simulator after its first boot"
    xcrun simctl spawn "$udid" defaults read -g AppleKeyboards || echo "(AppleKeyboards is not set)"
    xcrun simctl spawn "$udid" defaults read com.apple.keyboard.preferences || echo "(com.apple.keyboard.preferences is not set)"
    # A simulator discards settings written before its first boot, so the writes come after it.
    # This setting hides the one-time introduction to slide typing that covers the keys.
    xcrun simctl spawn "$udid" defaults write com.apple.keyboard.preferences DidShowContinuousPathIntroduction -bool true
    case "$task" in
      english) ;;
      pinyin)
        xcrun simctl spawn "$udid" defaults write -g AppleKeyboards -array "$pinyin_keyboard"
        xcrun simctl spawn "$udid" defaults write -g AppleKeyboardsExpanded -int 1
        xcrun simctl spawn "$udid" defaults write com.apple.keyboard.preferences KeyboardLastUsed -string "$pinyin_keyboard"
        ;;
      *) echo "unknown task: $task" >&2; exit 2 ;;
    esac
    xcrun simctl shutdown "$udid"
    xcrun simctl boot "$udid"
    xcrun simctl bootstatus "$udid" -b
    echo "== Keyboard settings after the restart"
    keyboards=$(xcrun simctl spawn "$udid" defaults read -g AppleKeyboards || echo "(AppleKeyboards is not set)")
    echo "$keyboards"
    xcrun simctl spawn "$udid" defaults read com.apple.keyboard.preferences
    if [ "$task" = pinyin ] && [[ "$keyboards" != *"Pinyin-Simplified"* ]]; then
      echo "the simulator did not keep the Pinyin keyboard" >&2
      exit 1
    fi
    ;;
  *)
    echo "unknown command: $command" >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash
# Fetches the native sources of the AOSP keyboard (LatinIME) and its stock English dictionary
# from android.googlesource.com, at one pinned commit, and checks both against known digests.
#
# Usage: fetch_sources.sh DESTINATION
# Result: DESTINATION/native/jni (Android.bp and src/) and DESTINATION/java/res/raw/main_en.dict
set -euo pipefail

REPOSITORY="https://android.googlesource.com/platform/packages/inputmethods/LatinIME"
# The commit of the tag android-16.0.0_r4.
COMMIT="efb2760302cb8824ae9fe36f993c48d5adc818b2"
# SHA-256 of Android.bp followed by every file under src/ in byte order of the paths.
SOURCES_SHA256="0a7d9057268b6283e16e1befb3aa335b9b763d03146049847b03ea49749ef4bd"
DICTIONARY_SHA256="581e0a428fff00d4ac574866596d6de9408bb76d1ce9626e34c887113713253f"

destination="${1:?usage: fetch_sources.sh DESTINATION}"
if [ -e "$destination" ]; then
    echo "fetch_sources.sh: $destination exists already" >&2
    exit 1
fi
mkdir -p "$destination/native/jni" "$destination/java/res/raw"

# The host limits anonymous requests at times, so a refused request is tried again.
fetch() {
    curl --fail --silent --show-error --location \
        --retry 6 --retry-delay 20 --retry-all-errors --output "$2" "$1"
}

fetch "$REPOSITORY/+archive/$COMMIT/native/jni.tar.gz" "$destination/native-jni.tar.gz"
tar -xzf "$destination/native-jni.tar.gz" -C "$destination/native/jni"
sources_sha256="$(cd "$destination/native/jni" && {
    cat Android.bp
    find src -type f -print0 | LC_ALL=C sort -z | xargs -0 cat
} | sha256sum | cut -d ' ' -f 1)"
if [ "$sources_sha256" != "$SOURCES_SHA256" ]; then
    echo "fetch_sources.sh: source digest $sources_sha256, expected $SOURCES_SHA256" >&2
    exit 1
fi

# Gitiles serves one file as base64 text.
fetch "$REPOSITORY/+/$COMMIT/java/res/raw/main_en.dict?format=TEXT" "$destination/main_en.dict.base64"
base64 --decode "$destination/main_en.dict.base64" > "$destination/java/res/raw/main_en.dict"
dictionary_sha256="$(sha256sum "$destination/java/res/raw/main_en.dict" | cut -d ' ' -f 1)"
if [ "$dictionary_sha256" != "$DICTIONARY_SHA256" ]; then
    echo "fetch_sources.sh: dictionary digest $dictionary_sha256, expected $DICTIONARY_SHA256" >&2
    exit 1
fi

echo "LatinIME commit $COMMIT (tag android-16.0.0_r4)"
echo "native/jni: $(find "$destination/native/jni/src" -type f | wc -l) files under src, digest $sources_sha256"
echo "java/res/raw/main_en.dict: $(stat --format=%s "$destination/java/res/raw/main_en.dict") bytes, sha256 $dictionary_sha256"

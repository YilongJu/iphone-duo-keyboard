#!/usr/bin/env bash
# Builds the native core of the AOSP keyboard (LatinIME) and the evaluation driver with g++.
#
# Usage: build.sh SOURCE_DIRECTORY OUTPUT_DIRECTORY
# SOURCE_DIRECTORY is the result of fetch_sources.sh. The driver lands at
# OUTPUT_DIRECTORY/latinime_driver.
#
# The core is the file group LATIN_IME_CORE_SRC_FILES of native/jni/Android.bp: 82 files under
# native/jni/src. The five JNI glue files next to Android.bp stay out of the build. The core
# includes jni.h for its types, so the build takes that header from a JDK.
set -euo pipefail

source_directory="${1:?usage: build.sh SOURCE_DIRECTORY OUTPUT_DIRECTORY}"
output_directory="${2:?usage: build.sh SOURCE_DIRECTORY OUTPUT_DIRECTORY}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
jni_directory="$(cd "$source_directory/native/jni" && pwd)"

: "${JAVA_HOME:?build.sh: JAVA_HOME must name a JDK, because the engine core includes jni.h}"
for header in "$JAVA_HOME/include/jni.h" "$JAVA_HOME/include/linux/jni_md.h"; do
    if [ ! -f "$header" ]; then
        echo "build.sh: $header is missing" >&2
        exit 1
    fi
done

mapfile -t sources < <(grep -o '"src/[^"]*\.cpp"' "$jni_directory/Android.bp" | tr -d '"' | LC_ALL=C sort -u)
if [ "${#sources[@]}" -ne 82 ]; then
    echo "build.sh: expected the 82 files of LATIN_IME_CORE_SRC_FILES, found ${#sources[@]}" >&2
    exit 1
fi

mkdir -p "$output_directory"
output_directory="$(cd "$output_directory" && pwd)"
objects="$output_directory/objects"
rm -rf "$objects"
mkdir -p "$objects"
failed_list="$objects/failed.txt"
: > "$failed_list"

# Compiles one core file, unchanged. -DHOST_TOOL is the flag that Android.bp gives to a host
# build. -w hides the warnings of the AOSP sources, which Android compiles with clang.
compile_core_file() {
    local source="$1"
    local object="$objects/${source//\//__}.o"
    if ! g++ -std=gnu++17 -O2 -DHOST_TOOL -w \
            -I"$jni_directory/src" -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/linux" \
            -c "$jni_directory/$source" -o "$object" 2> "$object.log"; then
        echo "$source" >> "$failed_list"
    fi
}
export -f compile_core_file
export jni_directory objects failed_list JAVA_HOME

# Every file is compiled, also after an error, so that one run shows all errors.
printf '%s\n' "${sources[@]}" | xargs -P "$(nproc)" -I{} bash -c 'compile_core_file "$1"' _ {}

status=0
mapfile -t failed < <(LC_ALL=C sort "$failed_list")
if [ "${#failed[@]}" -gt 0 ]; then
    status=1
    echo "build.sh: ${#failed[@]} of ${#sources[@]} core files do not compile:" >&2
    for source in "${failed[@]}"; do
        echo "=== $source" >&2
        head -n 60 "$objects/${source//\//__}.o.log" >&2
    done
fi

# The driver. The AOSP headers come in as system headers, so the warnings shown are the driver's.
driver_object="$output_directory/latinime_driver.o"
if ! g++ -std=gnu++17 -O2 -DHOST_TOOL -Wall -Wextra \
        -isystem "$jni_directory/src" -isystem "$JAVA_HOME/include" -isystem "$JAVA_HOME/include/linux" \
        -c "$here/latinime_driver.cpp" -o "$driver_object" 2> "$driver_object.log"; then
    status=1
    echo "build.sh: latinime_driver.cpp does not compile:" >&2
    head -n 150 "$driver_object.log" >&2
elif [ -s "$driver_object.log" ]; then
    echo "build.sh: warnings for latinime_driver.cpp:"
    head -n 60 "$driver_object.log"
fi

if [ "$status" -ne 0 ]; then
    exit "$status"
fi

# -rdynamic keeps the function names for the backtrace that the driver prints on a fatal signal.
g++ -O2 -rdynamic "$objects"/*.o "$driver_object" -o "$output_directory/latinime_driver"

echo "build.sh: built $output_directory/latinime_driver from ${#sources[@]} unchanged core files and latinime_driver.cpp"
core_bytes=0
for object in "$objects"/*.o; do
    core_bytes=$((core_bytes + $(stat --format=%s "$object")))
done
echo "build.sh: object files of the core: $core_bytes bytes; driver binary: $(stat --format=%s "$output_directory/latinime_driver") bytes"
size "$output_directory/latinime_driver"

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

# Compiles one core file. With `prelude` set, host_prelude.h goes in front of the file.
# -DHOST_TOOL is the flag that Android.bp gives to a host build. -w hides the warnings of the
# AOSP sources, which Android compiles with clang.
compile_core_file() {
    local source="$1"
    local object="$objects/${source//\//__}.o"
    local flags=(-std=gnu++17 -O2 -DHOST_TOOL -w
        -I"$jni_directory/src" -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/linux")
    if [ -n "${prelude:-}" ]; then
        flags+=(-include "$prelude")
    fi
    if ! g++ "${flags[@]}" -c "$jni_directory/$source" -o "$object" 2> "$object.log"; then
        echo "$source" >> "$failed_list"
    fi
}
export -f compile_core_file
export jni_directory objects JAVA_HOME

compile_all() {
    printf '%s\n' "$@" | xargs -P "$(nproc)" -I{} bash -c 'compile_core_file "$1"' _ {}
}

# First pass: every file as it is.
export failed_list="$objects/failed-as-is.txt"
export prelude=""
: > "$failed_list"
compile_all "${sources[@]}"
mapfile -t failed_as_is < <(LC_ALL=C sort "$failed_list")

# Second pass: the files of the first list again, with host_prelude.h in front.
failed_with_prelude=()
if [ "${#failed_as_is[@]}" -gt 0 ]; then
    echo "build.sh: ${#failed_as_is[@]} core files do not compile as they are with g++:"
    for source in "${failed_as_is[@]}"; do
        echo "--- $source"
        grep -m 3 'error' "$objects/${source//\//__}.o.log" || head -n 3 "$objects/${source//\//__}.o.log"
    done
    export failed_list="$objects/failed-with-prelude.txt"
    export prelude="$here/host_prelude.h"
    : > "$failed_list"
    compile_all "${failed_as_is[@]}"
    mapfile -t failed_with_prelude < <(LC_ALL=C sort "$failed_list")
fi

status=0
if [ "${#failed_with_prelude[@]}" -gt 0 ]; then
    status=1
    echo "build.sh: ${#failed_with_prelude[@]} core files do not compile with host_prelude.h either:" >&2
    for source in "${failed_with_prelude[@]}"; do
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

echo "build.sh: built $output_directory/latinime_driver from ${#sources[@]} core files and latinime_driver.cpp"
echo "build.sh: core files compiled with host_prelude.h in front: ${#failed_as_is[@]}"
for source in "${failed_as_is[@]}"; do
    echo "  $source"
done

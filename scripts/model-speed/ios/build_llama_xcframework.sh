#!/usr/bin/env bash
# Builds a llama.cpp xcframework for iOS (device and simulator) and macOS at a release tag, with
# the upstream script build-xcframework.sh of that release, for the speed test of
# docs/model-speed-design.md. Run it on a Mac with Xcode.
#
# Usage: build_llama_xcframework.sh TAG OUT_DIR ARCH
#   TAG    a release of https://github.com/ggml-org/llama.cpp, such as b12017
#   ARCH   the value of GGML_CPU_ARM_ARCH for the iOS device part only, such as
#          armv8.6-a+dotprod+i8mm, or "plain" for the upstream build without it. The upstream
#          script builds with GGML_NATIVE=OFF, so without ARCH the device part holds neither the
#          dot-product nor the i8mm kernels. The simulator and macOS parts hold two processor
#          kinds each (arm64 and x86_64), so they keep the upstream flags.
# The result is OUT_DIR/llama-TAG-ARCH.xcframework.zip.
set -euo pipefail
tag="$1"
out="$2"
arch="$3"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
src="$out/src-$tag"
if [ ! -d "$src/.git" ]; then
  git clone --quiet --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$src"
fi
cd "$src"
git checkout --quiet -- build-xcframework.sh
if [ "$arch" != plain ]; then
  # Adds the flag to the cmake call of build_ios_device, right after its architecture line.
  awk -v flag="        -DGGML_CPU_ARM_ARCH=$arch \\" '
    /^build_ios_device\(\) \{/ { inside = 1 }
    { print }
    inside && /-DCMAKE_OSX_ARCHITECTURES="arm64" \\/ { print flag; inside = 0; added = 1 }
    END { if (!added) { print "the device build of build-xcframework.sh has no architecture line" > "/dev/stderr"; exit 1 } }
  ' build-xcframework.sh > build-xcframework.patched.sh
  mv build-xcframework.patched.sh build-xcframework.sh
  chmod +x build-xcframework.sh
  grep -n "GGML_CPU_ARM_ARCH" build-xcframework.sh
fi
./build-xcframework.sh ios-device ios-sim macos > "$out/build-$tag-$arch.log" 2>&1 || {
  tail -n 60 "$out/build-$tag-$arch.log"
  exit 1
}
test -d build-apple/llama.xcframework
rm -f "$out/llama-$tag-$arch.xcframework.zip"
(cd build-apple && zip -qry "$out/llama-$tag-$arch.xcframework.zip" llama.xcframework)
echo "built $out/llama-$tag-$arch.xcframework.zip"

/*
 * Standard headers for a build of the AOSP LatinIME native core with g++ and GNU libstdc++.
 *
 * Android builds the core with clang and libc++. A libc++ header can pull in a second standard
 * header that the matching libstdc++ header leaves out. build.sh compiles each core file as it
 * is first. A file that does not compile that way is compiled again with this header in front
 * (g++ -include), and build.sh prints the names of those files.
 */
#ifndef DUO_LATINIME_HOST_PRELUDE_H
#define DUO_LATINIME_HOST_PRELUDE_H

#include <algorithm>
#include <climits>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#endif // DUO_LATINIME_HOST_PRELUDE_H

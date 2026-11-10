# Builds the typing-evaluation adapter against an installed libime.
#
# Packaged libime:      cmake -S . -B BUILD -DADAPTER_CXX_STANDARD=17
# libime from source:   cmake -S . -B BUILD -DADAPTER_CXX_STANDARD=20 -DCMAKE_PREFIX_PATH=PREFIX
cmake_minimum_required(VERSION 3.16)
project(libime_adapter LANGUAGES CXX)

set(ADAPTER_CXX_STANDARD "" CACHE STRING "C++ standard for the adapter: 17 for libime 1.1.5, 20 for libime 1.1.17")
if(NOT ADAPTER_CXX_STANDARD)
    message(FATAL_ERROR "Set -DADAPTER_CXX_STANDARD=17 or -DADAPTER_CXX_STANDARD=20.")
endif()

find_package(LibIMEPinyin REQUIRED)
if(NOT LibIMEPinyin_VERSION)
    message(FATAL_ERROR "find_package(LibIMEPinyin) did not report a version.")
endif()
message(STATUS "Adapter builds against LibIMEPinyin ${LibIMEPinyin_VERSION} from ${LibIMEPinyin_DIR}")

add_executable(libime_adapter libime_adapter.cpp)
set_target_properties(libime_adapter PROPERTIES
    CXX_STANDARD ${ADAPTER_CXX_STANDARD}
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF)
target_compile_definitions(libime_adapter PRIVATE ADAPTER_LIBIME_VERSION="${LibIMEPinyin_VERSION}")
# The flags Correction, L_R and Letter and the correction profile class were read in the 1.1.17 headers.
if(LibIMEPinyin_VERSION VERSION_GREATER_EQUAL 1.1.17)
    target_compile_definitions(libime_adapter PRIVATE ADAPTER_HAS_1_1_17_API=1)
else()
    target_compile_definitions(libime_adapter PRIVATE ADAPTER_HAS_1_1_17_API=0)
endif()
target_link_libraries(libime_adapter PRIVATE LibIME::Pinyin)

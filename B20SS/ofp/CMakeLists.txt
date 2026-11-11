cmake_minimum_required(VERSION 3.20)

project(fmofp_ofp
    VERSION 0.1.0
    DESCRIPTION "FMOFP operational flight program (C++ port)"
    LANGUAGES CXX)

if(NOT CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    message(FATAL_ERROR
        "Only GCC and Clang are supported (got ${CMAKE_CXX_COMPILER_ID}). "
        "On Windows use the MSYS2 UCRT64 toolchain; see README.md.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
endif()

option(OFP_BUILD_TESTS "Build the GoogleTest unit tests" ON)
option(OFP_COVERAGE "Instrument for gcov/gcovr" OFF)
option(OFP_SANITIZE
    "Build with AddressSanitizer and UndefinedBehaviorSanitizer (Linux; not available with MinGW GCC)" OFF)

include(cmake/flight_code.cmake)

# The ICD is the only source of bus message layouts; C++ is generated from it at
# build time (see icd/CMakeLists.txt). The generator is standard-library Python.
find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
set(OFP_ICD_XML "${CMAKE_CURRENT_SOURCE_DIR}/../icd/fmofp_icd.xml" CACHE FILEPATH "The bus ICD")
set(OFP_ICD_TOOL "${CMAKE_CURRENT_SOURCE_DIR}/../icd/tools/icd_tool.py")

if(OFP_BUILD_TESTS)
    find_package(GTest REQUIRED)
    enable_testing()
endif()

add_subdirectory(bus)
add_subdirectory(osal)
add_subdirectory(icd)
add_subdirectory(bc)
add_subdirectory(partitions)
if(OFP_BUILD_TESTS)
    find_package(Threads REQUIRED)
    add_subdirectory(tests)
endif()

# `cmake --build <dir> --target cppcheck` runs cppcheck over everything in the
# compile database except the tests and third-party headers.
find_program(OFP_CPPCHECK cppcheck)
if(OFP_CPPCHECK)
    add_custom_target(cppcheck
        COMMAND ${OFP_CPPCHECK}
            --project=${CMAKE_BINARY_DIR}/compile_commands.json
            --enable=warning,style,performance,portability
            --inline-suppr
            --suppress=missingIncludeSystem
            --suppress=*:*/tests/*
            --suppress=*:*_test.cpp
            --error-exitcode=1
            --quiet
        WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
        COMMENT "cppcheck over compile_commands.json"
        VERBATIM)
endif()

# `cmake --build <dir> --target coverage` after configuring with -DOFP_COVERAGE=ON.
# Runs the tests first, so it needs every test executable built.
find_program(OFP_GCOVR gcovr)
if(OFP_COVERAGE AND OFP_GCOVR AND OFP_BUILD_TESTS)
    # The flight code: the bus, the OSAL, the controller and every partition's logic. Left out: each process's
    # main.cpp, the stdin tools and the stub terminal, which the Python end-to-end and oracle tests exercise
    # (gcov does not see those runs), and the generated ICD code, which has its own generated round-trip tests.
    # cmake/coverage_check.py then holds every module (bus, osal, bc, partitions/<name>) to a floor of its own
    # lines (unit 30): OFP_COVERAGE_FLOOR for all, OFP_COVERAGE_FLOORS ("module=percent;...") for the few with a
    # stated reason to sit lower.
    set(OFP_COVERAGE_FLOOR 80 CACHE STRING "Line coverage every flight code module must reach, percent")
    set(OFP_COVERAGE_FLOORS "" CACHE STRING "Per-module floors, module=percent;module=percent")
    set(OFP_COVERAGE_FLOOR_ARGS "")
    foreach(module_floor IN LISTS OFP_COVERAGE_FLOORS)
        list(APPEND OFP_COVERAGE_FLOOR_ARGS --floor-for ${module_floor})
    endforeach()
    add_custom_target(coverage
        COMMAND ${CMAKE_CTEST_COMMAND} --output-on-failure
        COMMAND ${OFP_GCOVR} --root ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_BINARY_DIR}
            --filter ${CMAKE_CURRENT_SOURCE_DIR}/bus
            --filter ${CMAKE_CURRENT_SOURCE_DIR}/osal
            --filter ${CMAKE_CURRENT_SOURCE_DIR}/bc
            --filter ${CMAKE_CURRENT_SOURCE_DIR}/partitions
            --exclude ".*/main\\.cpp"
            --exclude ".*/tools/.*"
            --exclude ".*/utilities_tool/.*"
            --exclude ".*/rt_stub/.*"
            # GCC bug 68080: a counter read while a test's terminal thread runs can come out negative.
            --gcov-ignore-parse-errors=negative_hits.warn_once_per_file
            --print-summary --txt
            --json-summary ${CMAKE_BINARY_DIR}/coverage_summary.json
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/cmake/coverage_check.py
            ${CMAKE_BINARY_DIR}/coverage_summary.json --floor ${OFP_COVERAGE_FLOOR} ${OFP_COVERAGE_FLOOR_ARGS}
        WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
        COMMENT "Line and branch coverage of the flight code, module by module"
        VERBATIM)
    add_dependencies(coverage ofp_tests ofp_icd_roundtrip_test)
endif()

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(magic_wand_nina_b302 LANGUAGES C)

target_sources(app PRIVATE
    src/main.c
    ../../src/mw_gesture.c
    ../../src/mw_gesture_event_v2.c
    ../../src/mw_target_math.c
)
target_include_directories(app PRIVATE ../../include)
target_compile_features(app PRIVATE c_std_11)
target_compile_options(app PRIVATE
    -Wall
    -Wextra
    -Werror
    -Wpedantic
    -Wconversion
    -Wshadow
)

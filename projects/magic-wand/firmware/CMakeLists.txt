cmake_minimum_required(VERSION 3.20)
project(magic_wand_review_firmware VERSION 0.1.0 LANGUAGES C)

option(MW_HOST_REVIEW "Build the host-only review harness" ON)

add_library(mw_core STATIC
    src/mw_protocol.c
    src/mw_state_machine.c
    src/mw_gesture.c
)
target_include_directories(mw_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(mw_core PUBLIC c_std_11)

if(MSVC)
    target_compile_options(mw_core PRIVATE /W4 /WX)
else()
    target_compile_options(mw_core PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
endif()

if(MW_HOST_REVIEW)
    enable_testing()
    add_executable(mw_host_review src/main.c)
    target_link_libraries(mw_host_review PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_host_review PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_host_review PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_host_review COMMAND mw_host_review)
endif()

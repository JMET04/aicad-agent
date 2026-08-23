cmake_minimum_required(VERSION 3.20)
project(magic_wand_review_firmware VERSION 0.1.0 LANGUAGES C)

option(MW_HOST_REVIEW "Build the host-only review harness" ON)

add_library(mw_core STATIC
    src/mw_protocol.c
    src/mw_state_machine.c
    src/mw_gesture.c
    src/mw_gesture_event_v2.c
    src/mw_target_math.c
    src/mw_receiver_runtime.c
    src/mw_receiver_multichannel.c
    src/mw_pattern_renderer.c
    src/mw_effect_audio.c
    src/mw_effect_scheduler.c
)
target_include_directories(mw_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(mw_core PUBLIC c_std_11)

if(MSVC)
    target_compile_options(mw_core PRIVATE /W4 /WX)
else()
    target_compile_options(mw_core PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
endif()

if(MW_HOST_REVIEW)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    enable_testing()
    add_executable(mw_host_review src/main.c)
    target_link_libraries(mw_host_review PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_host_review PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_host_review PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_host_review COMMAND mw_host_review)

    add_executable(
        mw_effect_preview_exporter
        tools/export_effect_previews.c
    )
    target_link_libraries(mw_effect_preview_exporter PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_effect_preview_exporter PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_effect_preview_exporter PRIVATE
            -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow
        )
    endif()

    add_executable(mw_gesture_vectors tests/gesture_vectors.c)
    target_link_libraries(mw_gesture_vectors PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_gesture_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_gesture_vectors PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_gesture_vectors COMMAND mw_gesture_vectors)

    add_executable(mw_target_math tests/target_math.c)
    target_link_libraries(mw_target_math PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_target_math PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_target_math PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_target_math COMMAND mw_target_math)

    add_executable(mw_gesture_event_v2_vectors tests/gesture_event_v2_vectors.c)
    target_link_libraries(mw_gesture_event_v2_vectors PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_gesture_event_v2_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_gesture_event_v2_vectors PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_gesture_event_v2_vectors COMMAND mw_gesture_event_v2_vectors)

    add_executable(mw_receiver_runtime_vectors tests/receiver_runtime_vectors.c)
    target_link_libraries(mw_receiver_runtime_vectors PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_receiver_runtime_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_receiver_runtime_vectors PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_receiver_runtime_vectors COMMAND mw_receiver_runtime_vectors)

    add_executable(mw_receiver_multichannel_vectors tests/receiver_multichannel_vectors.c)
    target_link_libraries(mw_receiver_multichannel_vectors PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_receiver_multichannel_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_receiver_multichannel_vectors PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_receiver_multichannel_vectors COMMAND mw_receiver_multichannel_vectors)

    add_executable(mw_pattern_effect_vectors tests/pattern_effect_vectors.c)
    target_link_libraries(mw_pattern_effect_vectors PRIVATE mw_core)
    if(MSVC)
        target_compile_options(mw_pattern_effect_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_pattern_effect_vectors PRIVATE -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow)
    endif()
    add_test(NAME mw_pattern_effect_vectors COMMAND mw_pattern_effect_vectors)

    add_executable(mw_epoch_record_vectors
        target/receiver-effects/src/mw_epoch_record.c
        target/receiver-effects/tests/epoch_record_vectors.c
    )
    target_include_directories(mw_epoch_record_vectors PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/target/receiver-effects/src
    )
    target_compile_features(mw_epoch_record_vectors PRIVATE c_std_11)
    if(MSVC)
        target_compile_options(mw_epoch_record_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_epoch_record_vectors PRIVATE
            -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow
        )
    endif()
    add_test(NAME mw_epoch_record_vectors COMMAND mw_epoch_record_vectors)

    add_executable(mw_epoch_store_vectors
        target/receiver-effects/src/mw_epoch_record.c
        target/receiver-effects/src/mw_epoch_store.c
        target/receiver-effects/tests/epoch_store_vectors.c
    )
    target_include_directories(mw_epoch_store_vectors PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/target/receiver-effects/src
    )
    target_compile_features(mw_epoch_store_vectors PRIVATE c_std_11)
    if(MSVC)
        target_compile_options(mw_epoch_store_vectors PRIVATE /W4 /WX)
    else()
        target_compile_options(mw_epoch_store_vectors PRIVATE
            -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow
        )
    endif()
    add_test(NAME mw_epoch_store_vectors COMMAND mw_epoch_store_vectors)

    add_test(
        NAME mw_target_contract
        COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/target/zephyr/verify_target_contract.py
            --check-only
    )
endif()

cmake_minimum_required(VERSION 3.20)

set(RECEIVER_EFFECTS_DIR "${CMAKE_CURRENT_LIST_DIR}")

function(require_text file_path expected_text)
    file(READ "${file_path}" file_contents)
    string(FIND "${file_contents}" "${expected_text}" match_index)
    if(match_index EQUAL -1)
        message(FATAL_ERROR
            "${file_path} does not contain required contract text: ${expected_text}"
        )
    endif()
endfunction()

require_text("${RECEIVER_EFFECTS_DIR}/CMakeLists.txt" "if(NOT TARGET app)")
require_text("${RECEIVER_EFFECTS_DIR}/CMakeLists.txt" "src/mw_epoch_record.c")
require_text("${RECEIVER_EFFECTS_DIR}/CMakeLists.txt" "src/mw_epoch_store.c")
require_text("${RECEIVER_EFFECTS_DIR}/CMakeLists.txt" "src/mw_epoch_nvs.c")

file(READ "${RECEIVER_EFFECTS_DIR}/CMakeLists.txt" cmake_fragment)
string(REGEX MATCHALL "src/mw_epoch_[a-z_]+\\.c" epoch_sources "${cmake_fragment}")
list(LENGTH epoch_sources epoch_source_count)
if(NOT epoch_source_count EQUAL 3)
    message(FATAL_ERROR
        "receiver-effects CMake fragment must contain exactly three epoch sources"
    )
endif()

require_text(
    "${RECEIVER_EFFECTS_DIR}/src/mw_epoch_nvs.c"
    "DT_NODELABEL(mw_epoch_partition)"
)
require_text(
    "${RECEIVER_EFFECTS_DIR}/src/mw_epoch_nvs.c"
    "An enabled dedicated mw_epoch_partition devicetree node is required"
)

foreach(required_config IN ITEMS
    "CONFIG_FLASH=y"
    "CONFIG_FLASH_MAP=y"
    "CONFIG_FLASH_PAGE_LAYOUT=y"
    "CONFIG_NVS=y"
    "CONFIG_NVS_DATA_CRC=y"
    "CONFIG_MPU_ALLOW_FLASH_WRITE=y"
)
    require_text(
        "${RECEIVER_EFFECTS_DIR}/prj.conf"
        "${required_config}"
    )
endforeach()

require_text(
    "${RECEIVER_EFFECTS_DIR}/receiver-effects-overlay-contract.yaml"
    "exact_offset_and_size: BOARD_FLASH_MAP_REVIEW_REQUIRED"
)
require_text(
    "${RECEIVER_EFFECTS_DIR}/receiver-effects-overlay-contract.yaml"
    "status: OPEN"
)

message(STATUS "receiver-effects NVS source and open-gate contract verified")
